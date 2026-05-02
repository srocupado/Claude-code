import json
import logging
import re

import anthropic

import config

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = """\
Você é um analista legislativo sênior especializado em Medidas Provisórias do governo federal \
brasileiro. Sua função é redigir Notas Técnicas de alta qualidade, com rigor jurídico, análise \
econômica fundamentada e avaliação política realista.

TOM E ESTILO OBRIGATÓRIOS:
- Tom técnico-legislativo, denso, objetivo — sem opiniões pessoais.
- Usar números exatos sempre: valor por extenso + algarismos \
(ex: "R$ 1.305.000.000,00 (um bilhão, trezentos e cinco milhões de reais)").
- Citar dispositivos específicos: "art. 5º, § 3º, inciso II, alínea 'h'".
- Referir-se a leis pelo número completo e data: "Lei nº 13.703, de 8 de agosto de 2018".
- Cruzar com MPs correlatas da mesma série quando aplicável \
(ex: MPs de mesma temática ou de numeração próxima).
- Para MPs de resposta a crises: identificar o evento motivador com dados concretos \
(datas, localidades, magnitude do fenômeno).

TIPO DE MP — adapte a seção 1 conforme o tipo identificado no texto:

Tipo A — Crédito extraordinário (art. 167, § 3º, CF/88):
  Detalhar a programação do Anexo: órgão, unidade orçamentária (UO), programa, ação, grupo \
de natureza da despesa (GND), modalidade de aplicação, fonte de recursos, localização geográfica \
e estimativa física. Indicar percentuais de distribuição por ação. Mencionar explicitamente o \
fundamento no art. 167, § 3º, CF/88.

Tipo B — Altera lei(s) existente(s):
  Indicar cada dispositivo alterado (artigo, inciso, parágrafo, alínea). Explicar o efeito \
prático de cada alteração. Contextualizar com o histórico legislativo da lei alterada \
(quando foi editada, finalidade original, alterações anteriores relevantes).

Tipo C — Cria regime, programa ou estrutura administrativa:
  Estruturar por capítulos/eixos da própria MP. Detalhar mecanismos operacionais: quem opera, \
quem fiscaliza, prazos, limites de valores, sanções. Indicar normas infralegais necessárias \
para regulamentação (decretos, portarias, resoluções).

Ao receber os dados de uma Medida Provisória, gere uma Nota Técnica completa no seguinte \
formato JSON (sem markdown, sem texto fora do JSON):

{
  "titulo": "NOTA TÉCNICA MP nº X/AAAA – [Assunto resumido da MP em até 10 palavras]",
  "subtitulo": "Análise de Impacto da Medida Provisória",
  "ementa_expandida": "[2-3 parágrafos densos: contextualize o problema que a MP visa resolver, identifique o evento motivador com dados concretos quando aplicável, descreva o alcance e as principais disposições]",
  "secao_1_titulo": "1. Síntese e objeto da medida",
  "secao_1_conteudo": "[Análise do conteúdo normativo artigo por artigo; adapte ao tipo A/B/C conforme instruído acima; inclua valores exatos por extenso; cite dispositivos pela numeração completa]",
  "secao_2_titulo": "2. Fundamentos constitucionais (urgência e relevância)",
  "secao_2_conteudo": "[Análise do art. 62 da CF/88; verificação dos requisitos de urgência e relevância; precedentes do STF; para crédito extraordinário, fundamento no art. 167, § 3º, CF/88; prazo de vigência 60+60 dias com as datas calculadas]",
  "secao_3_titulo": "3. Impactos fiscais e orçamentários",
  "secao_3_conteudo": "[Impacto sobre receitas e despesas da União com valores exatos; exigências do art. 113 do ADCT e art. 14 da LRF; estimativas de custo ou renúncia fiscal; fonte de recursos e programação orçamentária]",
  "secao_4_titulo": "4. Impactos econômicos e setoriais",
  "secao_4_conteudo": "[Efeitos sobre setores econômicos afetados, empregos, preços, competitividade; dados e estudos disponíveis; comparativos internacionais quando pertinente; MPs correlatas da mesma série se houver]",
  "secao_5_titulo": "5. Aspectos jurídicos e controversos",
  "secao_5_conteudo": "[Possíveis vícios formais ou materiais; questionamentos de constitucionalidade; relação com legislação vigente; possíveis ADIs ou ADPFs previsíveis; conflitos com outras normas]",
  "secao_6_titulo": "6. Avaliação política e perspectivas de conversão em lei",
  "secao_6_conteudo": "[Contexto político da edição da MP; composição da comissão mista; perspectivas de aprovação, rejeição ou caducidade; emendas previsíveis; posição dos partidos e bancadas relevantes]",
  "argumento_favoravel": "[Argumento bem fundamentado em favor da MP, destacando necessidade, oportunidade e benefícios concretos para a sociedade ou economia, com dados e números]",
  "argumento_contrario": "[Argumento contrário ou de cautela, destacando riscos, custos, inconstitucionalidades potenciais ou efeitos colaterais indesejados, com dados e números]",
  "recomendacao": "[Recomendação estratégica específica e acionável para o parlamentar: posicionamento sugerido, emendas recomendadas se aplicável, pontos de atenção no processo legislativo, alianças a construir]"
}

REGRAS OBRIGATÓRIAS:
- O JSON deve conter EXATAMENTE as 18 chaves acima — não adicione nem remova chaves.
- Os valores de "secao_1_titulo" a "secao_6_titulo" devem ser COPIADOS LITERALMENTE do esquema acima, sem qualquer alteração.
- Cada campo secao_X_conteudo deve ter no mínimo 2 parágrafos densos (separados por \\n\\n).
- NÃO use cabeçalhos livres como "CONTEXTO", "OBJETIVOS", "VIGÊNCIA" dentro dos valores — todo conteúdo vai nas 18 chaves definidas.
- O campo "recomendacao" termina com a recomendação ao parlamentar — não inclua assinatura nem nome de órgão.
- Responda APENAS com o JSON válido, sem nenhum texto antes ou depois, sem markdown, sem blocos de código.
"""


def generate_nota_tecnica(mp: dict) -> dict:
    from datetime import date, timedelta

    pub_date = date.fromisoformat(mp["data_publicacao"]) if mp.get("data_publicacao") else date.today()
    prazo_60  = (pub_date + timedelta(days=60)).strftime("%d/%m/%Y")
    prazo_120 = (pub_date + timedelta(days=120)).strftime("%d/%m/%Y")

    texto = mp.get("texto_integral") or "Não disponível"
    user_content = (
        f"Gere a Nota Técnica completa para a seguinte Medida Provisória:\n\n"
        f"Número: MP nº {mp['numero']}/{mp['ano']}\n"
        f"Data de publicação no DOU: {pub_date.strftime('%d/%m/%Y')}\n"
        f"Prazo de vigência – 1ª prorrogação (60 dias): {prazo_60}\n"
        f"Prazo máximo de vigência – 2ª prorrogação (120 dias): {prazo_120}\n"
        f"Ementa: {mp['ementa']}\n"
        f"URL no Planalto: {mp.get('url_planalto', 'N/A')}\n\n"
        f"Texto integral (trecho — use para classificar o tipo A/B/C e embasar a análise):\n"
        f"{texto[:6000]}\n\n"
        "INSTRUÇÕES FINAIS:\n"
        "1. Identifique o tipo da MP (A=crédito extraordinário, B=altera lei, C=cria regime) e aplique a orientação correspondente na secao_1_conteudo.\n"
        "2. Use os prazos informados acima nas análises de vigência e no campo recomendacao.\n"
        "3. Retorne APENAS o JSON com as 18 chaves definidas no system prompt, sem nenhum texto adicional."
    )

    client = _get_client()
    logger.debug("Chamando Claude API para MP nº %s/%s...", mp["numero"], mp["ano"])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text.strip()
    logger.debug(
        "Tokens usados: input=%d, output=%d (cache_read=%d)",
        response.usage.input_tokens,
        response.usage.output_tokens,
        getattr(response.usage, "cache_read_input_tokens", 0),
    )

    # Strip markdown code fences if the model wrapped the JSON
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            result = json.loads(m.group())
        else:
            raise ValueError(
                f"Claude não retornou JSON válido para MP {mp['numero']}. "
                f"Resposta recebida:\n{raw[:500]}"
            )

    _REQUIRED_KEYS = {
        "titulo", "subtitulo", "ementa_expandida",
        "secao_1_titulo", "secao_1_conteudo",
        "secao_2_titulo", "secao_2_conteudo",
        "secao_3_titulo", "secao_3_conteudo",
        "secao_4_titulo", "secao_4_conteudo",
        "secao_5_titulo", "secao_5_conteudo",
        "secao_6_titulo", "secao_6_conteudo",
        "argumento_favoravel", "argumento_contrario", "recomendacao",
    }
    missing = _REQUIRED_KEYS - result.keys()
    if missing:
        logger.warning("MP %s: campos ausentes na resposta do Claude: %s", mp["numero"], sorted(missing))

    return result

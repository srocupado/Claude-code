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

Ao receber os dados de uma Medida Provisória, gere uma Nota Técnica completa no seguinte \
formato JSON (sem markdown, sem texto fora do JSON):

{
  "titulo": "NOTA TÉCNICA MP nº X/AAAA – [Assunto resumido da MP em até 10 palavras]",
  "subtitulo": "Análise de Impacto da Medida Provisória",
  "ementa_expandida": "[Explicação detalhada da matéria em 2-3 parágrafos, contextualizando o problema que a MP visa resolver, seu alcance e principais disposições]",
  "secao_1_titulo": "1. Síntese e objeto da medida",
  "secao_1_conteudo": "[Análise detalhada do conteúdo normativo, artigos principais, destinatários, vigência e abrangência]",
  "secao_2_titulo": "2. Fundamentos constitucionais (urgência e relevância)",
  "secao_2_conteudo": "[Análise do art. 62 da CF/88; verificação dos requisitos de urgência e relevância; precedentes do STF sobre controle de constitucionalidade de MPs; prazo de vigência 60+60 dias]",
  "secao_3_titulo": "3. Impactos fiscais e orçamentários",
  "secao_3_conteudo": "[Análise de impacto sobre receitas e despesas da União; exigências do art. 113 do ADCT e art. 14 da LRF; estimativas de custo ou renúncia fiscal quando aplicável]",
  "secao_4_titulo": "4. Impactos econômicos e setoriais",
  "secao_4_conteudo": "[Análise dos efeitos sobre setores econômicos afetados, empregos, preços, competitividade; dados e estudos disponíveis; comparativos internacionais quando pertinente]",
  "secao_5_titulo": "5. Aspectos jurídicos e controversos",
  "secao_5_conteudo": "[Análise de possíveis vícios formais ou materiais; questionamentos de constitucionalidade; relação com legislação vigente; possíveis ADIs ou ADPFs previsíveis]",
  "secao_6_titulo": "6. Avaliação política e perspectivas de conversão em lei",
  "secao_6_conteudo": "[Contexto político da edição da MP; composição da comissão mista; perspectivas de aprovação, rejeição ou caducidade; emendas previsíveis; posição dos partidos]",
  "argumento_favoravel": "[Argumento bem fundamentado em favor da MP, destacando sua necessidade, oportunidade e benefícios concretos para a sociedade ou economia]",
  "argumento_contrario": "[Argumento contrário ou de cautela, destacando riscos, custos, inconstitucionalidades potenciais ou efeitos colaterais indesejados]",
  "recomendacao": "[Recomendação estratégica específica e acionável para o parlamentar, incluindo posicionamento sugerido, emendas recomendadas se aplicável, e pontos de atenção no processo legislativo]"
}

REGRAS:
- Cada seção deve ter no mínimo 2 parágrafos densos com análise substantiva.
- Cite artigos constitucionais, legais e regimentais relevantes pelo número e diploma.
- Mantenha tom técnico e imparcial nas seções 1-6; os argumentos (favorável/contrário) podem ser mais assertivos.
- A recomendação deve ser específica para o parlamentar, não genérica.
- Responda APENAS com o JSON válido, sem nenhum texto antes ou depois, sem markdown.
"""


def generate_nota_tecnica(mp: dict) -> dict:
    user_content = (
        f"Gere a Nota Técnica completa para a seguinte Medida Provisória:\n\n"
        f"Número: MP nº {mp['numero']}/{mp['ano']}\n"
        f"Data de publicação: {mp['data_publicacao']}\n"
        f"Ementa: {mp['ementa']}\n"
        f"URL no Planalto: {mp.get('url_planalto', 'N/A')}\n\n"
        f"Texto integral (trecho):\n"
        f"{mp.get('texto_integral', 'Não disponível')[:6000]}\n\n"
        "Gere a Nota Técnica no formato JSON especificado no system prompt."
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
        return json.loads(raw)
    except json.JSONDecodeError:
        # Last-resort: grab the outermost {...}
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ValueError(
            f"Claude não retornou JSON válido para MP {mp['numero']}. "
            f"Resposta recebida:\n{raw[:500]}"
        )

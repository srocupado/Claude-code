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


# ── System prompt: semantic rules only (no JSON template) ────────────────────

SYSTEM_PROMPT = """\
Você é um analista legislativo sênior especializado em Medidas Provisórias do governo federal \
brasileiro. Sua função é redigir Notas Técnicas de alta qualidade com rigor jurídico, análise \
econômica fundamentada e avaliação política realista.

TOM E ESTILO:
- Tom técnico-legislativo, denso, objetivo — sem opiniões pessoais.
- Números sempre por extenso + algarismos: "R$ 500.000.000,00 (quinhentos milhões de reais)".
- Dispositivos pelo número completo: "art. 5º, § 3º, inciso II, alínea 'h'".
- Leis pelo número e data: "Lei nº 13.703, de 8 de agosto de 2018".
- Cruzar com MPs correlatas da mesma série quando aplicável.
- Para MPs de resposta a crises: identificar o evento motivador com dados concretos.

TIPO DE MP — adapte a análise do objeto conforme o tipo:
  Tipo A (crédito extraordinário): detalhar programação do Anexo (órgão, UO, programa, ação, \
GND, modalidade, fonte, localização, estimativa física), percentuais por ação, art. 167 §3º CF/88.
  Tipo B (altera leis): cada dispositivo alterado, efeito prático, histórico legislativo da lei.
  Tipo C (cria regime/programa): capítulos/eixos, mecanismos operacionais (quem opera, fiscaliza, \
prazos, limites, sanções), normas infralegais necessárias.

Cada campo de conteúdo deve ter no mínimo 2 parágrafos densos separados por \\n\\n. \
Cite artigos constitucionais e legais pelo número e diploma.
"""

# ── Tool schema: structure without template in the prompt ─────────────────────

_TOOL = {
    "name": "nota_tecnica",
    "description": "Gera a Nota Técnica completa da Medida Provisória.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {
                "type": "string",
                "description": "NOTA TÉCNICA MP nº X/AAAA – [assunto resumido em até 10 palavras]",
            },
            "subtitulo": {
                "type": "string",
                "description": "Sempre: 'Análise de Impacto da Medida Provisória'",
            },
            "ementa_expandida": {
                "type": "string",
                "description": (
                    "2-3 parágrafos (separados por \\n\\n): contextualize o problema que a MP visa "
                    "resolver, identifique o evento motivador com dados concretos quando aplicável, "
                    "descreva o alcance e as principais disposições."
                ),
            },
            "secao_1_conteudo": {
                "type": "string",
                "description": (
                    "Síntese e objeto da medida — análise artigo por artigo, adaptada ao Tipo A/B/C; "
                    "valores exatos por extenso; cite dispositivos pela numeração completa."
                ),
            },
            "secao_2_conteudo": {
                "type": "string",
                "description": (
                    "Fundamentos constitucionais — art. 62 CF/88, urgência e relevância, precedentes "
                    "do STF; para crédito extraordinário, art. 167 §3º CF/88; mencione os prazos "
                    "de vigência 60+60 dias com as datas calculadas."
                ),
            },
            "secao_3_conteudo": {
                "type": "string",
                "description": (
                    "Impactos fiscais e orçamentários — valores exatos; art. 113 do ADCT e art. 14 "
                    "da LRF; estimativas de custo ou renúncia fiscal; fonte de recursos."
                ),
            },
            "secao_4_conteudo": {
                "type": "string",
                "description": (
                    "Impactos econômicos e setoriais — setores afetados, empregos, preços, "
                    "competitividade; MPs correlatas da mesma série se houver."
                ),
            },
            "secao_5_conteudo": {
                "type": "string",
                "description": (
                    "Aspectos jurídicos e controversos — vícios formais ou materiais, "
                    "constitucionalidade, relação com legislação vigente, possíveis ADIs/ADPFs."
                ),
            },
            "secao_6_conteudo": {
                "type": "string",
                "description": (
                    "Avaliação política e perspectivas de conversão em lei — contexto político, "
                    "comissão mista, perspectivas de aprovação/rejeição/caducidade, emendas "
                    "previsíveis, posição dos partidos."
                ),
            },
            "argumento_favoravel": {
                "type": "string",
                "description": "Argumento em favor da MP com necessidade, oportunidade e benefícios concretos.",
            },
            "argumento_contrario": {
                "type": "string",
                "description": "Argumento de cautela: riscos, custos, inconstitucionalidades potenciais.",
            },
            "recomendacao": {
                "type": "string",
                "description": (
                    "Recomendação estratégica ao parlamentar: posicionamento, emendas sugeridas, "
                    "alianças, pontos de atenção. Não inclua assinatura."
                ),
            },
        },
        "required": [
            "titulo", "subtitulo", "ementa_expandida",
            "secao_1_conteudo", "secao_2_conteudo", "secao_3_conteudo",
            "secao_4_conteudo", "secao_5_conteudo", "secao_6_conteudo",
            "argumento_favoravel", "argumento_contrario", "recomendacao",
        ],
    },
}

# Fixed section titles (not generated by AI — always literal)
SECTION_TITLES = {
    "secao_1_titulo": "1. Síntese e objeto da medida",
    "secao_2_titulo": "2. Fundamentos constitucionais (urgência e relevância)",
    "secao_3_titulo": "3. Impactos fiscais e orçamentários",
    "secao_4_titulo": "4. Impactos econômicos e setoriais",
    "secao_5_titulo": "5. Aspectos jurídicos e controversos",
    "secao_6_titulo": "6. Avaliação política e perspectivas de conversão em lei",
}


def generate_nota_tecnica(mp: dict) -> dict:
    from datetime import date, timedelta

    pub_date  = date.fromisoformat(mp["data_publicacao"]) if mp.get("data_publicacao") else date.today()
    prazo_60  = (pub_date + timedelta(days=60)).strftime("%d/%m/%Y")
    prazo_120 = (pub_date + timedelta(days=120)).strftime("%d/%m/%Y")

    texto = mp.get("texto_integral") or "Não disponível"
    user_content = (
        f"MP nº {mp['numero']}/{mp['ano']}\n"
        f"Publicação: {pub_date.strftime('%d/%m/%Y')} | "
        f"1ª prorrogação: {prazo_60} | 2ª prorrogação: {prazo_120}\n"
        f"Ementa: {mp['ementa']}\n"
        f"URL: {mp.get('url_planalto', 'N/A')}\n\n"
        f"Texto (use para classificar Tipo A/B/C e embasar toda a análise):\n"
        f"{texto[:6000]}"
    )

    client = _get_client()
    logger.debug("Chamando Claude para MP nº %s/%s...", mp["numero"], mp["ano"])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "nota_tecnica"},
        messages=[{"role": "user", "content": user_content}],
    )

    logger.debug(
        "Tokens: input=%d output=%d cache_read=%d",
        response.usage.input_tokens,
        response.usage.output_tokens,
        getattr(response.usage, "cache_read_input_tokens", 0),
    )

    # tool_use response: content[0].input is already a parsed dict
    result = response.content[0].input

    # Merge fixed section titles
    result.update(SECTION_TITLES)

    missing = set(_TOOL["input_schema"]["required"]) - result.keys()
    if missing:
        logger.warning("MP %s: campos ausentes: %s", mp["numero"], sorted(missing))

    return result

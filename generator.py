import logging

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
brasileiro. Redige Notas Técnicas com rigor jurídico, linguagem técnico-legislativa densa e objetiva.

REGRAS DE ESCRITA:
- Tom técnico-legislativo, objetivo — sem opiniões pessoais.
- Leis pelo número e data: "Lei nº 11.977, de 7 de julho de 2009".
- Dispositivos pelo número completo: "art. 5º, § 1º-A, inciso II".
- Use travessões (—) para explicações incidentais.
- Cite MPs correlatas pelo número e ano quando aplicável.
- NÃO mencione quem assinou ou referendou a MP (Presidente da República, ministros signatários).

RESUMO (primeiro campo):
Um único parágrafo apresentando a MP: o que ela faz, qual lei altera ou regime cria, e qual o \
objetivo central. Baseie-se na ementa e no texto integral fornecidos.

ALTERAÇÕES LEGAIS (segundo campo):
Do segundo parágrafo em diante, descreva cada alteração legal promovida pela MP. Para cada \
dispositivo alterado ou criado:
- Cite o artigo, parágrafo e inciso da lei afetada (com número e data da lei).
- Explique o que muda na prática e quem é afetado.
- Quando relevante, narre o histórico da lei alterada e das MPs anteriores que já a modificaram.
- Aponte normas infralegais ainda necessárias para operacionalização.
Separe cada parágrafo com linha em branco (\\n\\n). Escreva quantos parágrafos forem necessários \
para cobrir todas as alterações — não resuma em excesso.
"""

_TOOL = {
    "name": "nota_tecnica",
    "description": "Gera o conteúdo textual da Nota Técnica da Medida Provisória.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {
                "type": "string",
                "description": "NOTA TÉCNICA MP nº X/AAAA – [assunto em até 10 palavras]",
            },
            "subtitulo": {
                "type": "string",
                "description": "Sempre: 'Análise de Impacto da Medida Provisória'",
            },
            "resumo": {
                "type": "string",
                "description": "Um parágrafo resumindo o teor da MP.",
            },
            "alteracoes": {
                "type": "string",
                "description": (
                    "Dois ou mais parágrafos (separados por \\n\\n) descrevendo as alterações "
                    "legais promovidas pela MP: artigos afetados, efeito prático, histórico "
                    "legislativo relevante, normas infralegais necessárias."
                ),
            },
        },
        "required": ["titulo", "subtitulo", "resumo", "alteracoes"],
    },
}


def generate_nota_tecnica(mp: dict) -> dict:
    texto = mp.get("texto_integral") or "Não disponível"
    user_content = (
        f"MP nº {mp['numero']}/{mp['ano']}\n"
        f"Ementa: {mp['ementa']}\n"
        f"URL: {mp.get('url_planalto', 'N/A')}\n\n"
        f"Texto integral (use para embasar a análise):\n"
        f"{texto[:6000]}"
    )

    client = _get_client()
    logger.debug("Chamando Claude para MP nº %s/%s...", mp["numero"], mp["ano"])

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
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

    result = response.content[0].input

    missing = set(_TOOL["input_schema"]["required"]) - result.keys()
    if missing:
        logger.warning("MP %s: campos ausentes: %s", mp["numero"], sorted(missing))

    return result

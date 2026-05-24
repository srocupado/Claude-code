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
- Leis pelo número e data completa: "Lei nº 11.977, de 7 de julho de 2009".
- Dispositivos pelo número completo: "art. 5º, § 1º-A, inciso II, alínea 'h'".
- Valores por extenso + algarismos: "R$ 1.305.000.000,00 (um bilhão, trezentos e cinco milhões de reais)".
- Use travessões (—) para explicações incidentais.
- Aspas curvas "…" no texto corrido; nunca aspas retas.
- Cite MPs correlatas pelo número e ano quando aplicável.
- NÃO mencione quem assinou ou referendou a MP (Presidente da República, ministros signatários).

GLOSSÁRIO (usar com precisão):
MPV = Medida Provisória | PLV = Projeto de Lei de Conversão | DOU = Diário Oficial da União
GND = Grupo de Natureza de Despesa | UO = Unidade Orçamentária
TAC = Transportador Autônomo de Cargas | TRRC = Transportador Rodoviário Remunerado de Cargas
RNTRC = Registro Nacional do Transportador Rodoviário de Cargas
CIOT = Código Identificador da Operação de Transporte
MDF-e = Manifesto Eletrônico de Documentos Fiscais
FGE = Fundo de Garantia à Exportação | FGCE = Fundo Garantidor do Comércio Exterior
FGO = Fundo Garantidor de Operações | FGHab = Fundo Garantidor da Habitação Popular
FAR = Fundo de Arrendamento Residencial | FNAC = Fundo Nacional de Aviação Civil
SUAS = Sistema Único de Assistência Social | MCMV = Minha Casa, Minha Vida
CadÚnico = Cadastro Único para Programas Sociais
ANTT = Agência Nacional de Transportes Terrestres
ANP = Agência Nacional do Petróleo, Gás Natural e Biocombustíveis
INCRA = Instituto Nacional de Colonização e Reforma Agrária
FUNAPOL = Fundo para Aparelhamento e Operacionalização das Atividades-fim da Polícia Federal
PPI = Preço de Paridade de Importação | FPE = Fundo de Participação dos Estados
CMN = Conselho Monetário Nacional | CTB = Código de Trânsito Brasileiro
CONTRAN = Conselho Nacional de Trânsito

SÉRIES TEMÁTICAS DE 2026 (cruzar referências no parágrafo de contexto quando pertinente):
- Calamidade Zona da Mata MG: MPs 1.337 (06/03), 1.338 (06/03), 1.339 (09/03), 1.342 (18/03) — total ~R$ 1,57 bi
- Crise dos Combustíveis: MPs 1.340 (12/03), 1.343 (19/03), 1.344 (19/03), 1.349 (07/04) — pacote ~R$ 31 bi
- Defesa Civil Nacional: MPs 1.339 (MG), 1.342 (MG), 1.346 (PR), 1.347 (nacional)
- Habitação/MCMV: MP 1.350 (15/04) — FGHab/melhorias habitacionais
- Plano Brasil Soberano: MP 1.345 (25/03) — FGE/FGCE + R$ 15 bi BNDES
- Moto-frete: MP 1.360 (19/05) — CTB + Lei 12.009/2009

ESTRUTURA OBRIGATÓRIA — 5 CAMPOS:

CAMPO contexto — 1º parágrafo:
Por que a MP foi editada. Obrigatoriamente: evento motivador concreto (crise, calamidade, \
demanda setorial, pacote governamental), dados quantitativos (número de afetados, valores, datas \
precisas), conexão com cenário político/econômico e referência a MPs correlatas anteriores da \
mesma série. Use o "CONTEXTO PESQUISADO" fornecido como base factual — nunca invente dados ou \
atribua falas sem fonte.

CAMPO dispositivos_centrais — 2º parágrafo:
Artigos principais com citação precisa ("O art. 1º…", "O § 3º do art. 5º…"), efeito jurídico, \
valores, prazos, condições.
- Para créditos extraordinários: detalhar o Anexo — órgão/UO, programa, ação, GND \
  (3=custeio, 4=investimentos, 5=inversões), modalidade (40=municípios, 90=direta), \
  fonte (3000=ordinários, 3042=Fundo Social, 3050, 3052), RP (0=financeira, 2=primária \
  discricionária), estimativa física (famílias, unidades, entes); fundamentar no art. 167, § 3º, CF.
- Para subvenções: R$/unidade, limite global, operador (ANP, BNDES, BB, Caixa), vigência, \
  condicionantes (repasse ao consumidor, habilitação), mecanismo de apuração e pagamento.
- Para alterações legislativas: "O art. 1º altera a Lei nº X, de Y, acrescentando o inciso Z \
  ao art. N, que [efeito]."

CAMPO dispositivos_adicionais — 3º parágrafo:
Artigos secundários, alterações em outras leis, disposições transitórias, regras de \
regulamentação e prazos para atos infralegais. Se a MP for curta, preencher com " " (espaço).

CAMPO sintese — 4º parágrafo:
Quadro resumo analítico: distribuição percentual de recursos por órgão/programa, eixos \
temáticos, análise da natureza da despesa (custeio vs. investimento vs. inversões). Se não \
aplicável, usar " ".

CAMPO fechamento — 5º parágrafo:
Contextualização política: reações de atores políticos/setoriais, conexão com pacote normativo \
mais amplo, impacto fiscal total com fontes de compensação, total acumulado da série temática, \
expectativas de regulamentação pendente (decretos, portarias, resoluções CMN/ANP/ANTT). \
Se não aplicável, usar " ".
"""

_TOOL = {
    "name": "nota_tecnica",
    "description": "Gera o conteúdo textual estruturado da Nota Técnica da Medida Provisória.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulo": {
                "type": "string",
                "description": "Nome oficial da MP: 'Medida Provisória nº X.XXX, de DD de mês de AAAA'",
            },
            "contexto": {
                "type": "string",
                "description": (
                    "1º parágrafo: por que a MP foi editada. "
                    "Evento motivador concreto, dados quantitativos, atores políticos, "
                    "MPs correlatas da mesma série. Baseado no CONTEXTO PESQUISADO fornecido."
                ),
            },
            "dispositivos_centrais": {
                "type": "string",
                "description": (
                    "2º parágrafo: artigos principais com citação precisa, efeito jurídico, "
                    "valores, prazos. Para créditos: detalhar Anexo conforme instruções. "
                    "Para subvenções: R$/unidade, limite, operador, condicionantes."
                ),
            },
            "dispositivos_adicionais": {
                "type": "string",
                "description": (
                    "3º parágrafo: artigos secundários, alterações em outras leis, "
                    "disposições transitórias, normas infralegais necessárias. "
                    "Use ' ' (espaço) se a MP for curta."
                ),
            },
            "sintese": {
                "type": "string",
                "description": (
                    "4º parágrafo: quadro resumo — distribuição de recursos, eixos temáticos, "
                    "natureza da despesa. Use ' ' se não aplicável."
                ),
            },
            "fechamento": {
                "type": "string",
                "description": (
                    "5º parágrafo: reações políticas/setoriais, impacto fiscal, total acumulado "
                    "da série, regulamentação pendente. Use ' ' se não aplicável."
                ),
            },
        },
        "required": ["titulo", "contexto", "dispositivos_centrais", "dispositivos_adicionais", "sintese", "fechamento"],
    },
}


def _research_context(mp: dict) -> str:
    """Calls Claude with web search to gather political/economic context for the MP."""
    client = _get_client()
    prompt = (
        f"Pesquise contexto sobre a Medida Provisória nº {mp['numero']}/{mp['ano']}.\n"
        f"Ementa: {mp.get('ementa', '')}\n\n"
        "Busque e sintetize em 3–4 parágrafos densos para uso em nota técnica legislativa:\n"
        "1. Evento ou crise que motivou a edição desta MP\n"
        "2. Atores políticos envolvidos (ministros, lideranças setoriais, governadores)\n"
        "3. Reações de setores afetados\n"
        "4. MPs correlatas anteriores sobre o mesmo tema\n"
        "5. Impacto fiscal estimado e fontes de compensação\n\n"
        "Tom técnico-legislativo. "
        "Fontes prioritárias: Planalto, Agência Gov, Câmara, Senado, mídia especializada."
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
        extra_headers={"anthropic-beta": "web-search-2025-03-05"},
    )
    return "\n\n".join(b.text for b in response.content if hasattr(b, "text") and b.text)


def generate_nota_tecnica(mp: dict) -> dict:
    context_research = ""
    if config.ENABLE_WEB_SEARCH:
        logger.info("  Pesquisando contexto via web search para MP nº %s/%s...", mp["numero"], mp["ano"])
        try:
            context_research = _research_context(mp)
            logger.debug("  Contexto pesquisado: %d chars.", len(context_research))
        except Exception:
            logger.exception("  Falha na pesquisa de contexto; continuando sem web search.")

    texto = mp.get("texto_integral") or "Não disponível"
    user_content = (
        f"MP nº {mp['numero']}/{mp['ano']}\n"
        f"Ementa: {mp['ementa']}\n"
        f"URL: {mp.get('url_planalto', 'N/A')}\n\n"
    )
    if context_research:
        user_content += (
            f"CONTEXTO PESQUISADO (use como base factual para o 1º parágrafo):\n"
            f"{context_research}\n\n"
        )
    user_content += (
        f"Texto integral da MP (use para análise dos dispositivos):\n"
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

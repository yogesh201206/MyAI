"""
core/task_classifier.py — Lightweight local task classification for AIZEN AI.

Phase 11: CODING, REASONING, FAST, CHAT, RESEARCH, VISION
Phase 14: DEBUGGING, CODE_GENERATION, CODE_REVIEW, FILE_ANALYSIS,
          SUMMARIZATION, STRUCTURED_OUTPUT, CREATIVE_WRITING,
          TRANSLATION, TERMINAL

All classification is:
  - Pure deterministic heuristics — zero network calls
  - Additive signal scoring with tie-break priority
  - Extensible by adding pattern groups and constants
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

import config

# ------------------------------------------------------------------
# TASK TYPE CONSTANTS
# ------------------------------------------------------------------

TASK_AUTO            = "AUTO"
TASK_CODING          = "CODING"
TASK_DEBUGGING       = "DEBUGGING"
TASK_CODE_GENERATION = "CODE_GENERATION"
TASK_CODE_REVIEW     = "CODE_REVIEW"
TASK_REASONING       = "REASONING"
TASK_FAST            = "FAST"
TASK_CHAT            = "CHAT"
TASK_RESEARCH        = "RESEARCH"
TASK_VISION          = "VISION"
TASK_FILE_ANALYSIS   = "FILE_ANALYSIS"
TASK_SUMMARIZATION   = "SUMMARIZATION"
TASK_STRUCTURED_OUT  = "STRUCTURED_OUTPUT"
TASK_CREATIVE        = "CREATIVE_WRITING"
TASK_TRANSLATION     = "TRANSLATION"
TASK_TERMINAL        = "TERMINAL"

VALID_MODES = {
    TASK_AUTO,
    TASK_CODING,
    TASK_DEBUGGING,
    TASK_CODE_GENERATION,
    TASK_CODE_REVIEW,
    TASK_REASONING,
    TASK_FAST,
    TASK_CHAT,
    TASK_RESEARCH,
    TASK_VISION,
    TASK_FILE_ANALYSIS,
    TASK_SUMMARIZATION,
    TASK_STRUCTURED_OUT,
    TASK_CREATIVE,
    TASK_TRANSLATION,
    TASK_TERMINAL,
}

# Canonical router modes understood by the `/mode` command
# (subset — the user-facing ones that map to router_mode)
USER_FACING_MODES = {
    TASK_AUTO, TASK_CODING, TASK_REASONING, TASK_FAST,
    TASK_CHAT, TASK_RESEARCH, TASK_VISION,
}


@dataclass
class ClassificationResult:
    task_type: str
    confidence: float
    matched_signals: List[str] = field(default_factory=list)
    mode_override: bool = False
    context_signals: List[str] = field(default_factory=list)
    explanation: str = ""


# ------------------------------------------------------------------
# SIGNAL PATTERN GROUPS
# ------------------------------------------------------------------

_DEBUGGING_PATTERNS = [
    (r"\b(debug|debugging|fix\s+(?:this|the)\s+(?:bug|error|exception|crash)|trace(?:back)?|stacktrace|stack\s+trace)\b", "debug keywords"),
    (r"\b(NullPointerException|IndexError|AttributeError|TypeError|KeyError|SyntaxError|NameError|ValueError|RuntimeError)\b", "named exception"),
    (r"\b(it'?s?\s+(?:broken|failing|crashing)|why\s+(?:is|does)\s+(?:this|it)\s+(?:fail|error|crash|break))\b", "crash description"),
    (r"\b(undefined|not\s+defined|is\s+not\s+a\s+function|cannot\s+read\s+propert(?:y|ies))\b", "js/ts error phrase"),
    (r"\b(exception\s+thrown|unhandled\s+exception|seg(?:mentation)?\s+fault|core\s+dump)\b", "runtime fault"),
    (r"\b(error\s+(?:message|log|output)|logs?\s+show(?:ing)?|traceback\s+below)\b", "error log context"),
]

_CODE_GENERATION_PATTERNS = [
    (r"\bwrite\s+(?:a|an|the|me\s+a)?\s*\w+\s*(?:function|class|method|module|service|api|endpoint|script|program|app)\b", "generate code request"),
    (r"\bimplement\s+(?:a|an)?\s+(?:REST|GraphQL|gRPC|CRUD|Spring|FastAPI|Express|Next\.?js)\b", "framework scaffold"),
    (r"\bwrite\s+(?:me\s+a?\s+)?(?:FastAPI|Flask|Django|Express|Spring|Rails|Gin)\b", "write framework endpoint"),
    (r"\b(write|generate|create|implement|build|code)\s+(?:a|an|the|me)?\s*(?:REST|GraphQL|gRPC|CRUD)\s+(?:endpoint|api|service|route)\b", "scaffold REST/API"),
    (r"\b(give\s+me\s+(?:the\s+)?code|show\s+me\s+(?:the\s+)?code|code\s+(?:for|to)\s+(?:do|implement|handle))\b", "give code request"),
    (r"\b(boilerplate|template|starter\s+code|skeleton|scaffold)\b", "boilerplate request"),
    (r"\bwrite\s+(?:a|the|me\s+a?\s+)?(?:function|method|class|test|unit\s+test|pytest|module)\s+(?:to|that|which|for)\b", "write function/test"),
    (r"\bgenerate\s+(?:a|the|me)?\s*(?:function|class|module|api|service)\b", "generate function/class"),
]

_CODE_REVIEW_PATTERNS = [
    (r"\b(review\s+(?:this|my|the)\s+code|code\s+review)\b", "code review request"),
    (r"\b(improve|optimize|refactor|clean\s+up|clean(?:er)?|simplify)\s+(?:this|my|the)\s+(?:code|function|method|class)\b", "improve/refactor request"),
    (r"\b(is\s+(?:this|my)\s+(?:code|approach|implementation)\s+(?:good|correct|efficient|clean|idiomatic))\b", "quality check"),
    (r"\b(best\s+(?:practice|practices)|anti-?pattern|code\s+smell|SOLID|KISS|DRY)\b", "best-practice query"),
    (r"\b(what'?s?\s+wrong\s+with\s+(?:this|my)\s+code|what\s+could\s+be\s+better)\b", "what's wrong query"),
]

_CODING_PATTERNS = [
    (r"\b(code|coding|program|programming|script)\b", "code keywords"),
    (r"\b(function|method|class|struct|interface|variable|array|object|dict|hashmap|loop|pointer)\b", "programming constructs"),
    (r"\b(python|java|javascript|typescript|c\+\+|golang|rust|ruby|php|kotlin|swift|scala)\b", "programming languages"),
    (r"\b(spring\s*boot|react|vue|angular|django|flask|fastapi|express|next\.?js|node\.?js|rails)\b", "frameworks"),
    (r"\b(sql|postgres|mysql|sqlite|mongodb|redis|graphql|rest\s*api|endpoint|json|xml|yaml)\b", "data/api technologies"),
    (r"\b(git|github|commit|repo|repository|merge|branch|pull\s*request|diff)\b", "version control"),
    (r"\b(npm|pip|maven|mvn|gradle|cargo|docker|kubernetes|k8s|cmake|make)\b", "build/dev tooling"),
    (r"\b(compile|compilation|syntax|refactor|test|unit\s*test|pytest|junit)\b", "software engineering"),
    (r"```[\w]*\n[\s\S]*?\n```", "code block in prompt"),
    (r"\b(def |class |import |from |public |private |fn |const |let |var )\b", "code syntax snippet"),
]

_FILE_ANALYSIS_PATTERNS = [
    (r"\b(analyze|analyse|explain|describe|summarize|review)\s+(?:this|my|the)\s+(?:file|document|pdf|doc|txt|log|csv|json|xml|code)\b", "analyze file"),
    (r"\b(what\s+(?:does|is)\s+(?:this|the)\s+(?:file|document|code|script|config|log)\s+(?:do|mean|contain|say))\b", "what does file do"),
    (r"\b(read\s+(?:this|the|my)\s+(?:file|document|pdf))\b", "read file request"),
    (r"\b(file\s+contents?|document\s+contents?|attached\s+(?:file|document))\b", "file content reference"),
]

_SUMMARIZATION_PATTERNS = [
    (r"\b(summarize|summarise|give\s+(?:a|me\s+a)\s+summary|write\s+a\s+summary|brief\s+(?:overview|summary))\b", "summarize request"),
    (r"\b(tl;?dr|TLDR|in\s+(?:brief|short)|key\s+(?:points?|takeaways?|highlights?))\b", "summary keywords"),
    (r"\b(what\s+(?:are|is)\s+the\s+main\s+(?:points?|ideas?|conclusions?))\b", "main points request"),
    (r"\b(condense|shorten|compress|distill|recap)\b", "condense request"),
]

_REASONING_PATTERNS = [
    (r"\b(analyze|analysis|deeply|deep\s+analysis)\b", "analysis request"),
    (r"\b(architecture|architectural|design\s+pattern|system\s+design)\b", "architecture design"),
    (r"\b(compare|comparison|tradeoff|trade-off|pros\s+and\s+cons|versus|vs\.?)\b", "comparative evaluation"),
    (r"\b(why\s+does|why\s+would|why\s+is|reason\s+for|underlying\s+reason)\b", "causality query"),
    (r"\b(plan|strategy|roadmap|step-by-step\s+plan|methodology)\b", "strategic planning"),
    (r"\b(logic|logical|deduce|derive|proof|mathematical\s+proof)\b", "formal logic"),
    (r"\b(complex|implications|consequences|hypothetical|counterfactual)\b", "complex reasoning"),
]

_STRUCTURED_OUTPUT_PATTERNS = [
    (r"\b(generate\s+(?:a|the)\s+(?:JSON|XML|YAML|CSV|markdown|table|schema|template))\b", "generate structured format"),
    (r"\b(output\s+(?:as|in)\s+(?:JSON|XML|YAML|CSV|markdown|table))\b", "output format specification"),
    (r"\b(fill\s+(?:in|out)\s+(?:this|the)\s+(?:template|form|schema))\b", "fill template"),
    (r"\b(extract\s+(?:the\s+)?(?:data|fields?|values?|entities|attributes)\s+(?:from|as)\s+(?:JSON|XML|table|CSV))\b", "extract structured data"),
    (r"\b(well-?formed|valid\s+JSON|parseable|machine\s*readable)\b", "machine-readable output"),
]

_CREATIVE_PATTERNS = [
    (r"\bwrite\s+(?:a|an|the)\s+(?:story|poem|essay|article|blog\s*post|email|letter|cover\s*letter|speech|script|novel|chapter)\b", "creative writing request"),
    (r"\b(creative|fictional|imaginative|narrative|plot|character|protagonist|antagonist)\b", "creative keywords"),
    (r"\b(brainstorm|ideate|come\s+up\s+with\s+ideas|generate\s+ideas)\b", "brainstorm request"),
    (r"\b(in\s+the\s+style\s+of|write\s+like|sound\s+like|as\s+if\s+written\s+by)\b", "style imitation"),
    (r"\bwrite\s+(?:a\s+)?(?:short\s+)?story\b", "write story"),
    (r"\b(poem|poetry|haiku|sonnet|limerick|prose|fiction|fantasy|sci-?fi)\b", "creative genre"),
]

_TRANSLATION_PATTERNS = [
    (r"\b(translate|translation|translating)\b", "translation keyword"),
    (r"\b(from\s+(?:english|spanish|french|german|chinese|japanese|korean|arabic|hindi|tamil|telugu|portuguese|russian|italian)\s+to)\b", "language pair translation"),
    (r"\b(in\s+(?:spanish|french|german|chinese|japanese|korean|arabic|hindi|tamil|telugu|portuguese|russian|italian))\b", "target language output"),
    (r"\b(how\s+do\s+you\s+say|what\s+is\s+the\s+(?:word|phrase|translation)\s+for)\b", "translation query"),
]

_TERMINAL_PATTERNS = [
    (r"\b(terminal|shell|bash|zsh|command\s*line|CLI|subprocess|cmd)\b", "terminal keywords"),
    (r"\b(run\s+(?:this|the|a|this\s+command)|execute\s+(?:this|the|a|a\s+command)|how\s+to\s+run)\b", "run command request"),
    (r"\b(chmod|chown|grep|awk|sed|curl|wget|ssh|scp|rsync|systemctl|service|apt|yum|brew)\b", "unix commands"),
    (r"\b(exit\s+code|return\s+code|stderr|stdout|pipe|redirect|stdin|crontab)\b", "terminal concepts"),
    (r"\b(why\s+(?:is|does)\s+(?:this\s+)?command\s+(?:fail|error|not\s+work)|command\s+not\s+found)\b", "command failure"),
    (r"\`[^`]+\`", "inline command in backticks"),
]

_FAST_PATTERNS = [
    (r"\b(what\s+is|what\s+are|define|definition\s+of|meaning\s+of)\b", "simple definition"),
    (r"\b(short\s+answer|briefly|in\s+one\s+sentence|in\s+short|quick\s+question)\b", "concise request"),
    (r"\b(synonym|antonym|translate|spelling|spell|capital\s+of)\b", "lookup fact"),
    (r"\b(yes\s+or\s+no|true\s+or\s+false|single\s+word)\b", "binary answer request"),
    (r"^([a-z0-9\s]{1,30}\?)$", "very short direct question"),
]

_RESEARCH_PATTERNS = [
    (r"\b(latest|current|recent|news|today|update|modern)\b", "recency query"),
    (r"\b(search|research|investigate|survey|overview\s+of\s+the\s+literature)\b", "literature/research inquiry"),
    (r"\b(market|industry\s+trends|state\s+of\s+the\s+art|sota)\b", "industry trends"),
    (r"\b(history\s+of|background\s+on|evolution\s+of)\b", "historical overview"),
    (r"\b(find\s+information|look\s+up\s+sources|citations)\b", "source gathering"),
]

_VISION_PATTERNS = [
    (r"\b(image|picture|photo|screenshot|diagram|illustration|chart|graph)\b", "visual reference"),
    (r"\b(look\s+at\s+this|in\s+this\s+image|ocr|read\s+this\s+screenshot)\b", "image analysis request"),
    (r"\b(visualize|visual\s+inspection)\b", "visualization demand"),
]

_CHAT_PATTERNS = [
    (r"^(hi|hello|hey|greetings|good\s+morning|good\s+afternoon|good\s+evening)\b", "greeting"),
    (r"\b(how\s+are\s+you|who\s+are\s+you|what\s+can\s+you\s+do|introduce\s+yourself)\b", "general banter"),
    (r"\b(thank\s+you|thanks|appreciate\s+it|bye|goodbye|see\s+you)\b", "conversational pleasantry"),
]


# Task priority order: higher-specificity tasks win tie-breaks
# Phase 14 tasks are more specific than Phase 11 tasks and win first
_TASK_PRIORITY_ORDER = [
    TASK_VISION,
    TASK_TERMINAL,
    TASK_DEBUGGING,
    TASK_CODE_GENERATION,
    TASK_CODE_REVIEW,
    TASK_SUMMARIZATION,
    TASK_FILE_ANALYSIS,
    TASK_STRUCTURED_OUT,
    TASK_TRANSLATION,
    TASK_CREATIVE,
    TASK_CODING,
    TASK_REASONING,
    TASK_RESEARCH,
    TASK_FAST,
    TASK_CHAT,
]

_ALL_PATTERN_GROUPS = [
    (TASK_VISION,          _VISION_PATTERNS),
    (TASK_TERMINAL,        _TERMINAL_PATTERNS),
    (TASK_DEBUGGING,       _DEBUGGING_PATTERNS),
    (TASK_CODE_GENERATION, _CODE_GENERATION_PATTERNS),
    (TASK_CODE_REVIEW,     _CODE_REVIEW_PATTERNS),
    (TASK_SUMMARIZATION,   _SUMMARIZATION_PATTERNS),
    (TASK_FILE_ANALYSIS,   _FILE_ANALYSIS_PATTERNS),
    (TASK_STRUCTURED_OUT,  _STRUCTURED_OUTPUT_PATTERNS),
    (TASK_TRANSLATION,     _TRANSLATION_PATTERNS),
    (TASK_CREATIVE,        _CREATIVE_PATTERNS),
    (TASK_CODING,          _CODING_PATTERNS),
    (TASK_REASONING,       _REASONING_PATTERNS),
    (TASK_RESEARCH,        _RESEARCH_PATTERNS),
    (TASK_FAST,            _FAST_PATTERNS),
    (TASK_CHAT,            _CHAT_PATTERNS),
]


# ------------------------------------------------------------------
# CLASSIFIER
# ------------------------------------------------------------------

def classify_task(
    prompt: str,
    context_details: Optional[dict] = None,
) -> ClassificationResult:
    """
    Classify a user prompt and optional context details into a task category.

    Phase 14 expansion: 9 new task types added (DEBUGGING, CODE_GENERATION,
    CODE_REVIEW, FILE_ANALYSIS, SUMMARIZATION, STRUCTURED_OUTPUT,
    CREATIVE_WRITING, TRANSLATION, TERMINAL).

    All classification is local, deterministic, and zero-cost.

    Args:
        prompt: Raw user query string.
        context_details: Optional dictionary containing runtime context:
            - attached_files: List[dict]
            - project_active: bool
            - rag_active: bool
            - has_image: bool

    Returns:
        ClassificationResult with task_type, confidence, signals, and explanation.
    """
    context_details = context_details or {}
    mode = getattr(config, "router_mode", TASK_AUTO).upper()

    # 1. Check for manual / explicit mode override
    if mode in VALID_MODES and mode != TASK_AUTO:
        has_image = context_details.get("has_image", False)
        if has_image and mode != TASK_VISION:
            return ClassificationResult(
                task_type=TASK_VISION,
                confidence=1.0,
                matched_signals=["image attached"],
                mode_override=False,
                context_signals=["image input present"],
                explanation=f"Overrode mode {mode} because visual input requires VISION task.",
            )
        return ClassificationResult(
            task_type=mode,
            confidence=1.0,
            matched_signals=[f"Mode forced to {mode}"],
            mode_override=True,
            explanation=f"User set router mode to {mode}.",
        )

    # 2. Extract context signals
    ctx_signals: List[str] = []
    coding_ctx_boost = 0.0
    research_ctx_boost = 0.0
    vision_ctx_boost = 0.0
    terminal_ctx_boost = 0.0
    file_analysis_boost = 0.0

    # Project mode
    if context_details.get("project_active") or (
        getattr(config, "project_mode", False) and getattr(config, "active_project_path", None)
    ):
        coding_ctx_boost += 1.5
        ctx_signals.append("active project coding context")

    # Terminal context
    if context_details.get("has_terminal") or getattr(config, "last_command_result", None) is not None:
        terminal_ctx_boost += 1.0
        ctx_signals.append("recent terminal output in context")

    # Attached files
    attached = context_details.get("attached_files")
    if attached is None:
        try:
            from core.file_manager import get_attached_files
            from core.chat_manager import get_current_chat
            cur = get_current_chat()
            if cur:
                attached = get_attached_files(cur)
        except Exception:
            attached = []

    if attached:
        for f in attached:
            fname = f.get("name", "").lower()
            if any(fname.endswith(ext) for ext in (
                ".py", ".java", ".js", ".ts", ".jsx", ".tsx",
                ".c", ".cpp", ".h", ".go", ".rs", ".sql",
                ".sh", ".json", ".xml", ".yml", ".yaml"
            )):
                coding_ctx_boost += 1.2
                ctx_signals.append(f"code file attached ({fname})")
            elif any(fname.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")):
                vision_ctx_boost += 3.0
                ctx_signals.append(f"image attached ({fname})")
            elif fname.endswith(".pdf"):
                research_ctx_boost += 1.0
                file_analysis_boost += 0.8
                ctx_signals.append(f"PDF document attached ({fname})")
            elif any(fname.endswith(ext) for ext in (".txt", ".md", ".log", ".csv")):
                file_analysis_boost += 0.6
                ctx_signals.append(f"text/document attached ({fname})")

    # RAG active
    if context_details.get("rag_active") or getattr(config, "rag_enabled", False):
        try:
            from core.kb_manager import get_kb_counts
            d_count, _ = get_kb_counts()
            if d_count > 0:
                research_ctx_boost += 0.8
                ctx_signals.append("knowledge base indexed")
        except Exception:
            pass

    # Image in prompt
    if context_details.get("has_image"):
        vision_ctx_boost += 5.0
        ctx_signals.append("image input present")

    # 3. Score all task types
    scores: dict[str, float] = {
        TASK_VISION:          vision_ctx_boost,
        TASK_TERMINAL:        terminal_ctx_boost,
        TASK_DEBUGGING:       0.0,
        TASK_CODE_GENERATION: 0.0,
        TASK_CODE_REVIEW:     0.0,
        TASK_SUMMARIZATION:   0.0,
        TASK_FILE_ANALYSIS:   file_analysis_boost,
        TASK_STRUCTURED_OUT:  0.0,
        TASK_TRANSLATION:     0.0,
        TASK_CREATIVE:        0.0,
        TASK_CODING:          coding_ctx_boost,
        TASK_REASONING:       0.0,
        TASK_RESEARCH:        research_ctx_boost,
        TASK_FAST:            0.0,
        TASK_CHAT:            0.2,  # baseline for natural chat
    }

    matched: dict[str, List[str]] = {k: [] for k in scores}
    p_clean = prompt.strip()

    def _match_patterns(patterns, task):
        for pat, desc in patterns:
            if re.search(pat, p_clean, re.IGNORECASE):
                scores[task] += 1.0
                matched[task].append(desc)

    for task_type, patterns in _ALL_PATTERN_GROUPS:
        _match_patterns(patterns, task_type)

    # Heuristics
    word_count = len(p_clean.split())

    # Short prompt without coding/reasoning/specific signals → FAST or CHAT
    if word_count < 12 and scores[TASK_CODING] <= coding_ctx_boost and scores[TASK_REASONING] == 0.0:
        greet_words = ["hi", "hello", "hey", "thanks", "bye"]
        if any(w in p_clean.lower().split() for w in greet_words):
            scores[TASK_CHAT] += 1.5
        else:
            scores[TASK_FAST] += 0.8
            matched[TASK_FAST].append("short query")

    # Long analytical prompt → boost REASONING
    if word_count > 200 and scores[TASK_REASONING] > 0.5:
        scores[TASK_REASONING] += 1.5
        matched[TASK_REASONING].append("long elaborate analytical query")

    # Debugging signals are more specific than generic coding — promote heavily
    if scores[TASK_DEBUGGING] >= 1.0:
        scores[TASK_DEBUGGING] += 1.5

    # Code generation is more specific than generic coding — promote heavily
    if scores[TASK_CODE_GENERATION] >= 1.0:
        scores[TASK_CODE_GENERATION] += 1.5

    # Code review is more specific than generic coding — promote
    if scores[TASK_CODE_REVIEW] >= 1.0:
        scores[TASK_CODE_REVIEW] += 1.0

    # Creative writing should win over generic FAST for write-a-story prompts
    if scores[TASK_CREATIVE] >= 1.0:
        scores[TASK_CREATIVE] += 1.5

    # 4. Determine winner using priority order
    best_task = TASK_CHAT
    best_score = -1.0

    for t in _TASK_PRIORITY_ORDER:
        s = scores.get(t, 0.0)
        if s > best_score:
            best_score = s
            best_task = t

    # Low-signal default → CHAT
    if best_score < 0.5:
        best_task = TASK_CHAT
        confidence = 0.5
    else:
        confidence = min(0.98, max(0.55, best_score / (best_score + 1.2)))

    # Phase 14: map granular sub-tasks back to a scorer-compatible base task
    # for model_ranker (which uses the Phase 11 task names for scoring dimensions)
    _RANKER_TASK_MAP = {
        TASK_DEBUGGING:       TASK_CODING,
        TASK_CODE_GENERATION: TASK_CODING,
        TASK_CODE_REVIEW:     TASK_CODING,
        TASK_FILE_ANALYSIS:   TASK_RESEARCH,
        TASK_SUMMARIZATION:   TASK_RESEARCH,
        TASK_STRUCTURED_OUT:  TASK_CODING,
        TASK_CREATIVE:        TASK_CHAT,
        TASK_TRANSLATION:     TASK_FAST,
        TASK_TERMINAL:        TASK_CODING,
    }
    ranker_task = _RANKER_TASK_MAP.get(best_task, best_task)

    active_signals = matched.get(best_task, [])
    explanation = (
        f"Classified as {best_task} (ranker: {ranker_task}, confidence: {confidence:.2f}) "
        f"based on {', '.join(active_signals + ctx_signals) if (active_signals or ctx_signals) else 'conversational default'}."
    )

    result = ClassificationResult(
        task_type=best_task,
        confidence=confidence,
        matched_signals=active_signals,
        mode_override=False,
        context_signals=ctx_signals,
        explanation=explanation,
    )
    # Attach ranker task as extra attribute (used by router/ranker)
    result.ranker_task = ranker_task  # type: ignore[attr-defined]
    return result

"""Domotica Fast-Path Decision & Execution Engine for HA System 1 (PRD v0.4.0 M1).

Provides sub-50ms deterministic local resolution of natural language smart home prompts into
Home Assistant service calls and OpenAI-compatible tool call payloads, enforcing strict
safety gates (FP-01..FP-18):
- Whole-token matching (FP-01)
- Imperatives only (FP-03, questions routed)
- Single-intent only (FP-04, multi-intent routed)
- No conditions or schedules (FP-05, routed)
- Numeric range bounds (FP-06)
- Targets never invented (FP-09)
- Sensitive domains excluded from fast path (FP-11 / D-5)
- Truthful execution status (FP-15) and localized confirmation speech (FP-16)
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from i18n import languages
from pydantic import BaseModel, Field
from resolver import HAResolver

logger = logging.getLogger("ha_system_1.domotica")


# Dynamically loaded multilingual dictionaries via LanguageRegistry
GENERIC_DOMAIN_NOUNS: Dict[str, Set[str]] = languages.get_aggregated_generic_nouns()
DOMAIN_KEYWORDS: Dict[str, Tuple[str, ...]] = languages.get_aggregated_domain_keywords()
ACTION_KEYWORDS: Dict[str, Tuple[str, ...]] = languages.get_aggregated_action_keywords()


# FP-11 / D-5: Sensitive domains that MUST NEVER take the fast path
SENSITIVE_DOMAINS = {"lock", "alarm_control_panel", "siren", "valve"}

# Pronouns & anaphoric references resolved in Elephant review mode
PRONOUN_TARGETS: Set[str] = {
    "ze", "hem", "het", "die", "deze", "dezelfde", "daar", "die lamp", "die lampen", "deze lamp", "deze lampen",
    "it", "them", "that", "those", "these", "the same", "there", "this light", "these lights",
}


class DomoticaAction(BaseModel):
    """Structured representation of a parsed smart home command."""

    is_domotica: bool = Field(description="Whether the prompt represents a home automation action")
    fast_path: bool = Field(default=False, description="Whether the command qualifies for sub-50ms zero-LLM execution")
    rejected_reason: Optional[str] = Field(default=None, description="Explicit RFC-compliant rejection reason code (FP-12)")
    domain: Optional[str] = Field(default=None, description="Home Assistant domain (light, switch, climate, cover)")
    service: Optional[str] = Field(default=None, description="Home Assistant service (turn_on, turn_off, etc.)")
    target_type: Optional[str] = Field(default=None, description="'area_id' or 'entity_id'")
    target_id: Optional[str] = Field(default=None, description="Exact target identifier")
    target_name: Optional[str] = Field(default=None, description="Extracted room or device name from prompt")
    service_data: Dict[str, Any] = Field(default_factory=dict, description="Parameters (brightness, temperature, etc.)")
    confidence: float = Field(default=0.0, description="Routing confidence score (0.0 - 1.0)")
    openai_tool_call: Optional[Dict[str, Any]] = Field(default=None, description="Standard OpenAI Tool Call payload for HA Assist")
    speech: Optional[str] = Field(default=None, description="Localized natural spoken confirmation text (FP-16)")
    executed: bool = Field(default=False, description="Whether the action was directly executed against HA API")
    execution_status: str = Field(default="none", description="Truthful execution status: 'none', 'confirmed', 'accepted', 'failed' (FP-15)")
    execution_result: Optional[Any] = Field(default=None, description="Result returned by Home Assistant API if executed")
    raw_input: Optional[str] = Field(default=None, description="Raw input text received")
    normalized_input: Optional[str] = Field(default=None, description="Normalized string evaluated")
    semantic_slots: Optional[Dict[str, Any]] = Field(default=None, description="Laya neural semantic slot predictions")
    gate_checks: Optional[Dict[str, Any]] = Field(default=None, description="Detailed trace of all gate checks evaluated")
    review_mode: str = Field(default="goldfish", description="'goldfish' (stateless atomic) or 'elephant' (contextual multi-turn)")
    context_applied: bool = Field(default=False, description="Whether previous turn context was resolved and applied")
    context_source: Optional[Dict[str, Any]] = Field(default=None, description="Metadata describing entity or state carried over from previous turns")


class DomoticaEngine:
    """Fast-Path rule and semantic engine for resolving domotica intents with strict safety gates."""

    def __init__(
        self,
        resolver: Optional[HAResolver] = None,
        router_engine: Optional[Any] = None,
        min_confidence: float = 0.70,
        fast_path_enabled: bool = True,
    ) -> None:
        self.resolver = resolver or HAResolver()
        self.router_engine = router_engine
        self.min_confidence = min_confidence
        self.fast_path_enabled = fast_path_enabled

    def classify_semantic_slots(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Run Laya System 1 single-forward-pass semantic slot extraction on Intel Arc XPU."""
        if not self.router_engine or not getattr(self.router_engine, "ready", False):
            return None
        router = getattr(self.router_engine, "router", None)
        if not router:
            return None
        try:
            from question_sets import get_question_set
            q_spec = get_question_set("domotica-v1")
            questions = q_spec["questions"]
            state = {"request": prompt.strip()}
            if hasattr(self.router_engine, "predict_locked"):
                res = self.router_engine.predict_locked(state, questions)
            else:
                res = router.predict(state, questions)
            answers = res.get("answers", {})
            return {
                "scope": answers.get("target_scope", {}).get("choice"),
                "scope_conf": float(answers.get("target_scope", {}).get("answer_confidence", 0.0)),
                "device_type": answers.get("device_type", {}).get("choice"),
                "device_type_conf": float(answers.get("device_type", {}).get("answer_confidence", 0.0)),
                "room": answers.get("room", {}).get("choice"),
                "room_conf": float(answers.get("room", {}).get("answer_confidence", 0.0)),
            }
        except Exception as exc:
            logger.debug("Laya semantic slot extraction skipped: %s", exc)
            return None

    def _parse_internal(
        self,
        prompt: str,
        recent_turns: Optional[List[Dict[str, Any]]] = None,
        review_mode: str = "goldfish",
    ) -> DomoticaAction:
        """Internal parser enforcing FP-01..FP-18 with Goldfish/Elephant review modes."""
        if not prompt or not prompt.strip():
            return DomoticaAction(
                is_domotica=False,
                confidence=0.0,
                rejected_reason="no_action",
                review_mode=review_mode,
            )

        clean_p = prompt.strip().lower()

        # 1. Detect Domain (FP-01 whole-token matching)
        detected_domain = None
        for dom, keywords in DOMAIN_KEYWORDS.items():
            if any(re.search(r"\b" + re.escape(k) + r"\b", clean_p) for k in keywords):
                detected_domain = dom
                break

        # 2. Detect Action (FP-01 whole-token matching)
        detected_action = None
        for action, keywords in ACTION_KEYWORDS.items():
            if any(re.search(r"\b" + re.escape(k) + r"\b", clean_p) for k in keywords):
                detected_action = action
                break

        # If neither domain nor action is detected, this is NOT a domotica command
        if not detected_domain and not detected_action:
            return DomoticaAction(
                is_domotica=False,
                confidence=0.0,
                rejected_reason="no_action",
                review_mode=review_mode,
            )

        # FP-03: Imperatives only. Questions never take the fast path
        if "?" in prompt:
            return DomoticaAction(
                is_domotica=True,
                fast_path=False,
                domain=detected_domain,
                rejected_reason="question",
                review_mode=review_mode,
            )

        leading_question_words = languages.get_aggregated_question_words()
        tokens = clean_p.split()
        if tokens and tokens[0] in leading_question_words:
            return DomoticaAction(
                is_domotica=True,
                fast_path=False,
                domain=detected_domain,
                rejected_reason="question",
                review_mode=review_mode,
            )

        # FP-04: Single intent only (reject multi-intent compound sentences)
        multi_intent_patterns = languages.get_aggregated_multi_intent_patterns()
        if any(re.search(pat, clean_p) for pat in multi_intent_patterns):
            return DomoticaAction(
                is_domotica=True,
                fast_path=False,
                domain=detected_domain,
                rejected_reason="multi_intent",
                review_mode=review_mode,
            )

        # FP-05: Negations, conditions, schedules never take fast path
        condition_patterns = languages.get_aggregated_condition_patterns()
        if any(re.search(pat, clean_p) for pat in condition_patterns):
            return DomoticaAction(
                is_domotica=True,
                fast_path=False,
                domain=detected_domain,
                rejected_reason="conditional",
                review_mode=review_mode,
            )

        # FP-11 / D-5: Sensitive devices never take the fast path
        if detected_domain in SENSITIVE_DOMAINS:
            return DomoticaAction(
                is_domotica=True,
                fast_path=False,
                domain=detected_domain,
                rejected_reason="sensitive_target",
                review_mode=review_mode,
            )

        # RG-03: If mirror is older than max_staleness_minutes, auto-sync and check
        if self.resolver.is_stale:
            if self.resolver.is_configured:
                self.resolver.sync(force=True)
            if self.resolver.is_stale:
                return DomoticaAction(
                    is_domotica=True,
                    fast_path=False,
                    domain=detected_domain,
                    service=detected_action,
                    rejected_reason="mirror_stale",
                    review_mode=review_mode,
                )

        # Normalize cover actions to standard cover domain services
        if detected_domain == "cover":
            if detected_action in ("turn_on", "open_cover"):
                detected_action = "open_cover"
            elif detected_action in ("turn_off", "close_cover"):
                detected_action = "close_cover"

        # If domain is not explicitly stated in prompt, check for Elephant context or pronoun references
        if not detected_domain and detected_action:
            if review_mode == "elephant" and recent_turns:
                for turn in reversed(recent_turns):
                    if turn.get("domain"):
                        detected_domain = turn.get("domain")
                        break
            if not detected_domain:
                tokens_set = set(clean_p.split())
                if tokens_set & PRONOUN_TARGETS:
                    return DomoticaAction(
                        is_domotica=True,
                        fast_path=False,
                        rejected_reason="unknown_target",
                        review_mode=review_mode,
                    )
                return DomoticaAction(
                    is_domotica=False,
                    confidence=0.1,
                    rejected_reason="no_action",
                    review_mode=review_mode,
                )

        if not detected_domain or not detected_action:
            return DomoticaAction(
                is_domotica=False,
                confidence=0.1,
                rejected_reason="no_action",
                review_mode=review_mode,
            )

        # 3. Extract Target Name (room or entity words)
        target_tokens = []
        skip_words = {
            "doe", "zet", "schakel", "maak", "de", "het", "een", "in", "op",
            "bij", "van", "naar", "alsjeblieft", "graag", "even", "alle",
            "allemaal", "al", "mijn", "onze",
        }
        generic_nouns = GENERIC_DOMAIN_NOUNS.get(detected_domain, set())
        action_kw_set = {k for keywords in ACTION_KEYWORDS.values() for k in keywords}

        for w in tokens:
            w_clean = re.sub(r"[^\w]", "", w)
            if not w_clean or any(c.isdigit() for c in w_clean):
                continue
            if w_clean in skip_words or w_clean in generic_nouns or w_clean in action_kw_set:
                continue
            target_tokens.append(w_clean)

        extracted_target = " ".join(target_tokens).strip()

        # 4. Extract Parameters & Validate Bounds (FP-06)
        service_data: Dict[str, Any] = {}
        if detected_domain == "climate":
            m_temp = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:graden|graad|celsius|°c)?", clean_p)
            if m_temp:
                try:
                    val = float(m_temp.group(1).replace(",", "."))
                    if 10.0 <= val <= 32.0:
                        service_data["temperature"] = val
                        detected_action = "set_temperature"
                    else:
                        return DomoticaAction(
                            is_domotica=True,
                            fast_path=False,
                            domain="climate",
                            rejected_reason="out_of_range",
                        )
                except ValueError:
                    pass
        elif detected_domain == "light":
            m_pct = re.search(r"(\d+)\s*(?:%|procent)", clean_p)
            if m_pct:
                try:
                    pct = int(m_pct.group(1))
                    if 1 <= pct <= 100:
                        service_data["brightness_pct"] = pct
                    else:
                        return DomoticaAction(
                            is_domotica=True,
                            fast_path=False,
                            domain="light",
                            rejected_reason="out_of_range",
                        )
                except ValueError:
                    pass

        # 5. Semantic Slot Disambiguation via Laya (Intel Arc XPU)
        slots = self.classify_semantic_slots(prompt)
        target_type = None
        target_id = None
        overall_conf = 0.95

        # Whole-home scope detection (e.g. "turn off all lights in the house", "doe alle lampen in huis uit")
        whole_home_markers = (
            "in the house", "in het huis", "in huis", "throughout the house", "in all rooms",
            "all lights in the house", "all lights in house", "alle lampen in huis", "alle lampen in het huis",
            "overal in huis", "overal in het huis",
        )
        has_specific_room = bool(slots and slots.get("room") and slots["room"] != "unspecified")
        is_whole_home = not has_specific_room and (
            any(m in clean_p for m in whole_home_markers)
            or (slots and slots.get("scope") == "entire_area" and any(w in clean_p.split() for w in ("house", "huis", "home", "overal")))
        )

        if is_whole_home:
            target_type = "area_id" if "huiswijd" in self.resolver._area_name_map else "domain_all"
            target_id = self.resolver._area_name_map.get("huiswijd", "all")
            extracted_target = "alle lampen in huis" if detected_domain == "light" else "huis"
            overall_conf = 0.98
        elif slots and slots.get("room") and slots["room"] != "unspecified":
            s_room = slots["room"]
            s_scope = slots.get("scope")
            s_dev = slots.get("device_type")
            r_conf = slots.get("room_conf", 0.0)
            d_conf = slots.get("device_type_conf", 0.0)

            # Conservative Gating (D-3): If confidence is below threshold, safely escalate to upstream LLM
            if r_conf < self.min_confidence or (s_scope == "specific_device" and d_conf < self.min_confidence):
                return DomoticaAction(
                    is_domotica=True,
                    fast_path=False,
                    domain=detected_domain,
                    service=detected_action,
                    target_name=extracted_target,
                    service_data=service_data,
                    rejected_reason="low_confidence",
                )

            if s_scope == "entire_area":
                target_type = "area_id"
                target_id = self.resolver._area_name_map.get(s_room, s_room)
                overall_conf = max(overall_conf, slots.get("scope_conf", 0.95))
            elif s_scope == "specific_device" and s_dev and s_dev != "general_light":
                dev_kw = {
                    "led_strip": ("gordijnen", "led", "strip", "ledstrip"),
                    "spots": ("spots", "spot", "dimmer"),
                    "cover": ("jaloezie", "gordijn", "rolluik", "shutter"),
                }.get(s_dev, (s_dev,))

                candidates = self.resolver.list_entities_for_domain(detected_domain)
                for cand in candidates:
                    eid = cand["entity_id"].lower()
                    fn = str(cand.get("friendly_name") or "").lower()
                    if s_room in eid or s_room in fn:
                        if any(kw in eid or kw in fn for kw in dev_kw):
                            target_type = "entity_id"
                            target_id = cand["entity_id"]
                            extracted_target = f"{s_dev} {s_room}"
                            overall_conf = max(overall_conf, slots.get("device_type_conf", 0.95))
                            break

        # Fallback to rule-based entity resolver if slots didn't pinpoint entity
        if not target_id:
            target_type, target_id, res_conf = self.resolver.resolve_target(
                domain=detected_domain,
                target_name=extracted_target,
            )
            if target_id:
                overall_conf = res_conf

        # Contextual Anaphora & Pronoun Resolution (Elephant Review Mode)
        context_applied = False
        context_source = None
        if review_mode == "elephant" and recent_turns and not target_id:
            tokens_set = set(clean_p.split())
            is_anaphoric = (
                bool(tokens_set & PRONOUN_TARGETS)
                or (extracted_target and extracted_target in PRONOUN_TARGETS)
                or not extracted_target
            )
            if is_anaphoric:
                for idx, turn in enumerate(reversed(recent_turns)):
                    prev_target_id = turn.get("target_id")
                    if prev_target_id:
                        target_id = prev_target_id
                        target_type = turn.get("target_type", "entity_id")
                        if not detected_domain or detected_domain == "light":
                            detected_domain = turn.get("domain", detected_domain or "light")
                        extracted_target = turn.get("target_name") or prev_target_id
                        context_applied = True
                        context_source = {
                            "turn_offset": idx + 1,
                            "target_id": prev_target_id,
                            "target_type": target_type,
                            "target_name": extracted_target,
                            "domain": detected_domain,
                            "reason": "anaphora_pronoun_resolution",
                        }
                        overall_conf = 0.96
                        break

        if not target_id:
            # FP-09: Targets are NEVER invented. Route to LLM if target is unknown.
            return DomoticaAction(
                is_domotica=True,
                fast_path=False,
                domain=detected_domain,
                service=detected_action,
                target_name=extracted_target,
                service_data=service_data,
                rejected_reason="unknown_target",
                review_mode=review_mode,
                context_applied=context_applied,
                context_source=context_source,
            )

        # 6. Format Standard OpenAI Tool Call for Home Assistant Assist (FP-13)
        ha_fn_name = "HassTurnOn" if detected_action in ("turn_on", "open_cover") else "HassTurnOff"
        if detected_action == "set_temperature":
            ha_fn_name = "HassClimateSetTemperature"
        elif detected_domain == "media_player":
            ha_fn_name = "HassMediaPause" if detected_action == "media_pause" else "HassMediaUnpause"

        tool_args: Dict[str, Any] = dict(service_data)
        if target_type == "area_id":
            tool_args["area"] = target_id
            if detected_domain:
                tool_args["domain"] = detected_domain
        elif target_type == "entity_id":
            tool_args["name"] = target_id
        elif target_type == "domain_all":
            if detected_domain:
                tool_args["domain"] = detected_domain

        tool_call = {
            "id": f"call_hasys1_{int(time.time()*1000) % 1000000}",
            "type": "function",
            "function": {
                "name": ha_fn_name,
                "arguments": tool_args,
            },
        }

        # 7. Localized Natural Speech Confirmation Template (FP-16)
        detected_lang = languages.detect_language(prompt)
        is_multiple = (target_type in ("area_id", "domain_all") and detected_domain == "light") or "lampen" in clean_p or "lights" in clean_p
        if target_type == "domain_all" or is_whole_home:
            display_target = "alle lampen in huis" if detected_lang == "nl" else "all lights in the house"
        elif target_type == "area_id":
            if detected_lang == "nl":
                display_target = f"alle lampen in de {target_id}" if detected_domain == "light" else f"{detected_domain} in {target_id}"
            else:
                display_target = f"all lights in {target_id}" if detected_domain == "light" else f"{detected_domain} in {target_id}"
        else:
            display_target = extracted_target or detected_domain

        speech = languages.format_speech(
            action=detected_action,
            target_name=display_target,
            lang=detected_lang,
            is_multiple=is_multiple,
            extra={"temperature": service_data.get("temperature", "")},
        )

        return DomoticaAction(
            is_domotica=True,
            fast_path=self.fast_path_enabled,
            domain=detected_domain,
            service=detected_action,
            target_type=target_type,
            target_id=target_id,
            target_name=extracted_target,
            service_data=service_data,
            confidence=overall_conf,
            openai_tool_call=tool_call,
            speech=speech,
            executed=False,
            execution_status="none",
            semantic_slots=slots,
            review_mode=review_mode,
            context_applied=context_applied,
            context_source=context_source,
        )

    def parse(
        self,
        prompt: str,
        recent_turns: Optional[List[Dict[str, Any]]] = None,
        review_mode: str = "goldfish",
    ) -> DomoticaAction:
        """Public parser returning DomoticaAction enriched with gate checks and semantic trace."""
        action = self._parse_internal(prompt, recent_turns=recent_turns, review_mode=review_mode)
        action.raw_input = prompt
        clean_p = prompt.strip().lower() if prompt else ""
        action.normalized_input = clean_p

        tokens = clean_p.split()

        action.gate_checks = {
            "has_input": bool(prompt and prompt.strip()),
            "is_imperative": not ("?" in prompt or (tokens and tokens[0] in languages.get_aggregated_question_words())),
            "is_single_intent": not any(re.search(pat, clean_p) for pat in languages.get_aggregated_multi_intent_patterns()),
            "no_conditions": not any(re.search(pat, clean_p) for pat in languages.get_aggregated_condition_patterns()),
            "not_sensitive": action.domain not in SENSITIVE_DOMAINS if action.domain else True,
            "fast_path_qualified": action.fast_path,
            "review_mode": review_mode,
            "context_applied": action.context_applied,
        }
        return action

    def route_and_execute(
        self,
        prompt: str,
        execute: bool = False,
        recent_turns: Optional[List[Dict[str, Any]]] = None,
        review_mode: str = "goldfish",
    ) -> DomoticaAction:
        """Route natural language prompt and optionally execute service call against HA."""
        action = self.parse(prompt, recent_turns=recent_turns, review_mode=review_mode)
        if execute and action.fast_path and action.domain and action.service and action.target_type and action.target_id:
            success, res = self.resolver.execute_service(
                domain=action.domain,
                service=action.service,
                target_type=action.target_type,
                target_id=action.target_id,
                service_data=action.service_data,
            )
            action.executed = success
            action.execution_result = res
            action.execution_status = "confirmed" if success else "failed"
        return action

"""Multilingual Language Pack Registry for HA System 1 Fast-Path & Laya Router."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

logger = logging.getLogger("ha_system_1.i18n")

LANGUAGES_DIR = Path(__file__).parent / "languages"
CUSTOM_LANGUAGES_DIR = Path("/addon_configs/local_ha_system_1/languages")


class LanguagePack:
    """Encapsulates vocabulary, grammar rules, speech templates, and criteria for one language."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.code: str = str(data.get("language", "en")).lower()
        self.name: str = str(data.get("name", self.code))
        self.generic_nouns: Dict[str, Set[str]] = {
            dom: set(words) for dom, words in data.get("generic_nouns", {}).items()
        }
        self.domain_keywords: Dict[str, Tuple[str, ...]] = {
            dom: tuple(words) for dom, words in data.get("domain_keywords", {}).items()
        }
        self.action_keywords: Dict[str, Tuple[str, ...]] = {
            act: tuple(words) for act, words in data.get("action_keywords", {}).items()
        }
        self.question_words: Tuple[str, ...] = tuple(data.get("question_words", []))
        self.multi_intent_patterns: Tuple[str, ...] = tuple(data.get("multi_intent_patterns", []))
        self.condition_patterns: Tuple[str, ...] = tuple(data.get("condition_patterns", []))
        self.speech_templates: Dict[str, str] = dict(data.get("speech_templates", {}))
        self.laya_criteria: Dict[str, str] = dict(data.get("laya_criteria", {}))


class LanguageRegistry:
    """Registry managing built-in and user-provided language packs."""

    def __init__(self, extra_dirs: Optional[List[Path]] = None) -> None:
        self.packs: Dict[str, LanguagePack] = {}
        self.default_lang = "nl"
        search_dirs = [LANGUAGES_DIR]
        if extra_dirs:
            search_dirs.extend(extra_dirs)
        if CUSTOM_LANGUAGES_DIR.exists():
            search_dirs.append(CUSTOM_LANGUAGES_DIR)

        for s_dir in search_dirs:
            if not s_dir.exists():
                continue
            for yml_path in sorted(s_dir.glob("*.yaml")):
                try:
                    with open(yml_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict) and "language" in data:
                        pack = LanguagePack(data)
                        self.packs[pack.code] = pack
                        logger.info("Loaded language pack '%s' (%s) from %s", pack.code, pack.name, yml_path)
                except Exception as exc:
                    logger.warning("Failed loading language pack from %s: %s", yml_path, exc)

        # Fallback to English if no packs loaded
        if not self.packs:
            logger.warning("No language packs found; initializing fallback english pack.")
            self.packs["en"] = LanguagePack({"language": "en", "name": "English"})

    def get_aggregated_domain_keywords(self) -> Dict[str, Tuple[str, ...]]:
        """Combine domain trigger keywords across all loaded languages."""
        combined: Dict[str, List[str]] = {}
        for pack in self.packs.values():
            for dom, kws in pack.domain_keywords.items():
                combined.setdefault(dom, []).extend(kws)
        return {dom: tuple(dict.fromkeys(kws)) for dom, kws in combined.items()}

    def get_aggregated_action_keywords(self) -> Dict[str, Tuple[str, ...]]:
        """Combine action keywords across all loaded languages."""
        combined: Dict[str, List[str]] = {}
        for pack in self.packs.values():
            for act, kws in pack.action_keywords.items():
                combined.setdefault(act, []).extend(kws)
        return {act: tuple(dict.fromkeys(kws)) for act, kws in combined.items()}

    def get_aggregated_generic_nouns(self) -> Dict[str, Set[str]]:
        """Combine generic category nouns across all loaded languages."""
        combined: Dict[str, Set[str]] = {}
        for pack in self.packs.values():
            for dom, nouns in pack.generic_nouns.items():
                combined.setdefault(dom, set()).update(nouns)
        return combined

    def get_aggregated_question_words(self) -> Tuple[str, ...]:
        """Combine question words across all languages for imperative safety gating."""
        words: List[str] = []
        for pack in self.packs.values():
            words.extend(pack.question_words)
        return tuple(dict.fromkeys(words))

    def get_aggregated_multi_intent_patterns(self) -> Tuple[str, ...]:
        """Combine multi-intent regex patterns across all languages."""
        patterns: List[str] = []
        for pack in self.packs.values():
            patterns.extend(pack.multi_intent_patterns)
        return tuple(dict.fromkeys(patterns))

    def get_aggregated_condition_patterns(self) -> Tuple[str, ...]:
        """Combine conditional and temporal regex patterns across all languages."""
        patterns: List[str] = []
        for pack in self.packs.values():
            patterns.extend(pack.condition_patterns)
        return tuple(dict.fromkeys(patterns))

    def detect_language(self, text: str) -> str:
        """Simple deterministic detector to pick best language pack for speech output."""
        clean = text.lower()
        dutch_markers = ("doe", "zet", "uit", "aan", "lampen", "licht", "verwarming", "graden", "de", "het")
        if any(f" {m} " in f" {clean} " for m in dutch_markers):
            return "nl"
        return "en" if "en" in self.packs else list(self.packs.keys())[0]

    def format_speech(
        self,
        action: str,
        target_name: str,
        lang: Optional[str] = None,
        is_multiple: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Format spoken natural language feedback matching the prompt's language."""
        extra = extra or {}
        active_lang = lang or self.default_lang
        pack = self.packs.get(active_lang) or self.packs.get(self.default_lang) or list(self.packs.values())[0]
        templates = pack.speech_templates

        verb = templates.get("verb_are", "zijn") if is_multiple else templates.get("verb_is", "is")
        if action in templates:
            tpl = templates[action]
            return tpl.format(target=target_name, verb=verb, **extra)

        generic_tpl = templates.get("generic", "Oké, {service} uitgevoerd voor {target}.")
        return generic_tpl.format(service=action, target=target_name, **extra)

    def get_multilingual_criteria(self, family: str, base_english: str) -> str:
        """Merge language-specific semantic criteria into a single prompt for Laya Router."""
        parts = [base_english]
        for pack in self.packs.values():
            if family in pack.laya_criteria and pack.laya_criteria[family] not in base_english:
                parts.append(pack.laya_criteria[family])
        return ", ".join(parts)


# Global singleton instance
languages = LanguageRegistry()

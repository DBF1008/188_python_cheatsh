"""
Queries routing and caching.

Exports:

    get_topics_list()
    get_answers()
"""

import random
import re
from typing import Any, Dict, List

import cache
import adapter.cheat_sheets
import adapter.cmd
import adapter.internal
import adapter.latenz
import adapter.learnxiny
import adapter.question
import adapter.rosetta
from config import CONFIG


class Router(object):
    """
    Implementation of query routing. Routing is based on `routing_table`
    and the data exported by the adapters (functions `get_list()` and `is_found()`).

    `get_topics_list()` returns available topics (accessible at /:list).
    `get_answer_dict()` return answer for the query.
    """

    def __init__(self):

        self._cached_topics_list = []
        self._cached_topic_type = {}

        adapter_class = adapter.all_adapters(as_dict=True)

        active_adapters = set(CONFIG["adapters.active"] + CONFIG["adapters.mandatory"])

        self._adapter = {
            "internal": adapter.internal.InternalPages(
                get_topic_type=self.get_topic_type, get_topics_list=self.get_topics_list
            ),
            "unknown": adapter.internal.UnknownPages(
                get_topic_type=self.get_topic_type, get_topics_list=self.get_topics_list
            ),
        }

        for by_name in active_adapters:
            if by_name not in self._adapter:
                self._adapter[by_name] = adapter_class[by_name]()

        self._topic_list = {key: obj.get_list() for key, obj in self._adapter.items()}

        self.routing_table = CONFIG["routing.main"]
        self.routing_table = (
            CONFIG["routing.pre"] + self.routing_table + CONFIG["routing.post"]
        )

    def get_topics_list(self, skip_dirs=False, skip_internal=False):
        """
        List of topics returned on /:list
        """

        if self._cached_topics_list:
            return self._cached_topics_list

        skip = ["fosdem"]
        if skip_dirs:
            skip.append("cheat.sheets dir")
        if skip_internal:
            skip.append("internal")
        sources_to_merge = [x for x in self._adapter if x not in skip]

        answer = {}
        for key in sources_to_merge:
            answer.update({name: key for name in self._topic_list[key]})
        answer = sorted(set(answer.keys()))

        self._cached_topics_list = answer
        return answer

    def get_topic_type(self, topic: str) -> List[str]:
        """
        Return list of topic types for `topic`
        or ["unknown"] if topic can't be determined.
        """

        def __get_topic_type(topic: str) -> List[str]:
            result = []
            for regexp, route in self.routing_table:
                if re.search(regexp, topic):
                    if route in self._adapter:
                        if self._adapter[route].is_found(topic):
                            result.append(route)
                    else:
                        result.append(route)
            if not result:
                return [CONFIG["routing.default"]]

            # cut the default route off, if there are more than one route found
            if len(result) > 1:
                return result[:-1]
            return result

        if topic not in self._cached_topic_type:
            self._cached_topic_type[topic] = __get_topic_type(topic)
        return self._cached_topic_type[topic]

    def _get_page_dict(self, query, topic_type, request_options=None):
        """
        Return answer_dict for the `query`.
        """
        return self._adapter[topic_type].get_page_dict(
            query, request_options=request_options
        )

    def handle_if_random_request(self, topic):
        """
        Check if the `query` is a :random one,
        if yes we check its correctness and then randomly select a topic,
        based on the provided prefix.

        """

        def __select_random_topic(prefix, topic_list):
            # Here we remove the special cases
            cleaned_topic_list = [
                x for x in topic_list if "/" not in x and ":" not in x
            ]

            # Here we still check that cleaned_topic_list in not empty
            if not cleaned_topic_list:
                return prefix

            random_topic = random.choice(cleaned_topic_list)
            return prefix + random_topic

        if topic.endswith("/:random") or topic.lstrip("/") == ":random":
            # We strip the :random part and see if the query is valid by running a get_topics_list()
            if topic.lstrip("/") == ":random":
                topic = topic.lstrip("/")
            prefix = topic[:-7]

            topic_list = [
                x[len(prefix) :] for x in self.get_topics_list() if x.startswith(prefix)
            ]

            if "" in topic_list:
                topic_list.remove("")

            if topic_list:
                # This is a correct formatted random query like /cpp/:random as the topic_list is not empty.
                random_topic = __select_random_topic(prefix, topic_list)
                return random_topic
            else:
                # This is a wrongly formatted random query like /xyxyxy/:random as the topic_list is empty
                # we just strip the /:random and let the already implemented logic handle it.
                wrongly_formatted_random = topic[:-8]
                return wrongly_formatted_random

        # Here if not a random request, we just forward the topic
        return topic

    def get_answers(
        self, topic: str, request_options: Dict[str, str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find cheat sheets for the topic.

        Args:
            `topic` (str):    the name of the topic of the cheat sheet

        Returns:
            [answer_dict]:    list of answers (dictionaries)
        """

        # if topic specified as <topic_type>:<topic>,
        # cut <topic_type> off
        topic_type = ""
        if re.match("[^/]+:", topic):
            topic_type, topic = topic.split(":", 1)

        topic = self.handle_if_random_request(topic)
        topic_types = self.get_topic_type(topic)

        # if topic_type is specified explicitly,
        # show pages only of that type
        if topic_type and topic_type in topic_types:
            topic_types = [topic_type]

        # 'question' queries are pretty expensive, that's why they should be handled
        # in a special way:
        # we do not drop the old style cache entries and try to reuse them if possible
        if topic_types == ["question"]:
            answer = cache.get("q:" + topic)
            if answer:
                if isinstance(answer, dict):
                    return [answer]
                return [
                    {
                        "topic": topic,
                        "topic_type": "question",
                        "answer": answer,
                        "format": "text+code",
                    }
                ]

            answer = self._get_page_dict(
                topic, topic_types[0], request_options=request_options
            )
            if answer.get("cache", True):
                cache.put("q:" + topic, answer)
            return [answer]

        # Try to find cacheable queries in the cache.
        # If answer was not found in the cache, resolve it in a normal way and save in the cache
        answers = []
        for topic_type in topic_types:

            cache_entry_name = f"{topic_type}:{topic}"
            cache_needed = self._adapter[topic_type].is_cache_needed()

            if cache_needed:
                answer = cache.get(cache_entry_name)
                if not isinstance(answer, dict):
                    answer = None
                if answer:
                    answers.append(answer)
                    continue

            answer = self._get_page_dict(
                topic, topic_type, request_options=request_options
            )
            if isinstance(answer, dict):
                if "cache" in answer:
                    cache_needed = answer["cache"]

            if cache_needed and answer:
                cache.put(cache_entry_name, answer)

            answers.append(answer)

        return answers

    def get_query_diagnostics(self, topic, request_options=None):
        """
        Return a read-only diagnostics dict explaining how `topic` is routed.

        The result reproduces the decision flow of `get_answers()` (explicit
        `<topic_type>:` split, `:random` handling, topic-type resolution and
        explicit narrowing) and adds a per-rule routing trace, the final
        adapter order, a read-only cache probe and a human-readable explanation
        of the branch that is taken (internal / unknown / question / content).

        No cheat sheets are fetched: `_get_page_dict()` is never called and the
        cache is only read, never written.
        """

        diag = {
            "topic": topic,
            "explicit_topic_type": None,
            "explicit_applied": False,
            "topic_after_type_split": topic,
            "random_request": False,
            "topic_after_random": topic,
            "routing_table_trace": [],
            "raw_selected": [],
            "default_applied": False,
            "trimmed_last": False,
            "topic_types": [],
            "adapter_order": [],
            "cache": [],
            "branch": {},
        }

        # 1. explicit "<topic_type>:<topic>" split (same as get_answers)
        explicit_topic_type = ""
        if re.match("[^/]+:", topic):
            explicit_topic_type, topic = topic.split(":", 1)
        diag["explicit_topic_type"] = explicit_topic_type or None
        diag["topic_after_type_split"] = topic

        # 2. :random handling (same as get_answers)
        diag["random_request"] = (
            topic.endswith("/:random") or topic.lstrip("/") == ":random"
        )
        topic = self.handle_if_random_request(topic)
        diag["topic_after_random"] = topic

        # 3. authoritative topic types
        topic_types = self.get_topic_type(topic)

        # 4. per-rule routing trace, reproducing the append rule of
        #    Router.get_topic_type.__get_topic_type (regex match AND
        #    (route is not an adapter OR adapter.is_found))
        raw_selected = []
        for regexp, route in self.routing_table:
            regex_matched = bool(re.search(regexp, topic))
            is_adapter = route in self._adapter
            found = None
            selected = False
            if regex_matched:
                if is_adapter:
                    found = self._adapter[route].is_found(topic)
                    selected = bool(found)
                else:
                    selected = True
            if selected:
                raw_selected.append(route)
            diag["routing_table_trace"].append(
                {
                    "regexp": regexp,
                    "route": route,
                    "regex_matched": regex_matched,
                    "is_adapter": is_adapter,
                    "is_found": found,
                    "selected": selected,
                }
            )
        diag["raw_selected"] = raw_selected
        diag["default_applied"] = not raw_selected
        # get_topic_type drops the last selected route when more than one matched
        diag["trimmed_last"] = len(raw_selected) > 1

        # 5. explicit narrowing (same as get_answers)
        if explicit_topic_type and explicit_topic_type in topic_types:
            topic_types = [explicit_topic_type]
            diag["explicit_applied"] = True
        diag["topic_types"] = list(topic_types)
        diag["adapter_order"] = list(topic_types)

        # 6. read-only cache probe, mirroring the cache keys of get_answers
        diag["cache"] = self._probe_cache(topic, topic_types)

        # 7. branch explanation
        diag["branch"] = self._diagnose_branch(
            topic_types, raw_selected, explicit_topic_type, diag["explicit_applied"]
        )

        return diag

    def _probe_cache(self, topic, topic_types):
        """
        Read-only cache probe for the resolved `topic_types`.
        Never writes the cache. Returns a list of per-entry dicts.
        """

        cache_off = CONFIG.get("cache.type") != "redis"

        def _probe(key):
            if cache_off:
                return False, "disabled"
            try:
                value = cache.get(key)
            except Exception:  # pylint: disable=broad-except
                # cache backend (redis) unreachable - diagnostics must not crash
                return False, "unavailable"
            hit = value is not None
            return hit, ("hit" if hit else "miss")

        # 'question' answers use a dedicated "q:" cache key (see get_answers)
        if topic_types == ["question"]:
            key = "q:" + topic
            hit, status = _probe(key)
            return [
                {
                    "topic_type": "question",
                    "cache_entry_name": key,
                    "cache_needed": True,
                    "cache_hit": hit,
                    "cache_status": status,
                }
            ]

        entries = []
        for topic_type in topic_types:
            key = "%s:%s" % (topic_type, topic)
            cache_needed = self._adapter[topic_type].is_cache_needed()
            if not cache_needed:
                entries.append(
                    {
                        "topic_type": topic_type,
                        "cache_entry_name": key,
                        "cache_needed": False,
                        "cache_hit": False,
                        "cache_status": "disabled",
                    }
                )
                continue
            hit, status = _probe(key)
            entries.append(
                {
                    "topic_type": topic_type,
                    "cache_entry_name": key,
                    "cache_needed": True,
                    "cache_hit": hit,
                    "cache_status": status,
                }
            )
        return entries

    def _diagnose_branch(
        self, topic_types, raw_selected, explicit_topic_type, explicit_applied
    ):
        """
        Build a human-readable explanation of why `topic_types` was chosen.
        """

        default_route = CONFIG["routing.default"]
        primary = topic_types[0] if topic_types else None
        is_unknown = "unknown" in topic_types
        is_internal = primary == "internal"

        reasons = []
        if explicit_applied:
            reasons.append(
                "Explicit topic_type '%s' was requested and matched, so only that "
                "adapter is used." % explicit_topic_type
            )
        if not raw_selected:
            reasons.append(
                "No routing rule selected an adapter, so the default route '%s' is used."
                % default_route
            )
        elif is_unknown:
            reasons.append(
                "The catch-all post route ('^[^/ +]*$' -> unknown) matched; the "
                "'unknown' adapter always reports found and returns fuzzy topic "
                "suggestions."
            )
        elif is_internal:
            reasons.append(
                "An internal route ('^:' or '/:list$') matched and the 'internal' "
                "adapter found the page."
            )
        else:
            reasons.append(
                "Resolved to content adapter(s): %s." % ", ".join(topic_types)
            )

        return {
            "primary_topic_type": primary,
            "is_internal": is_internal,
            "is_unknown": is_unknown,
            "is_question": primary == default_route,
            "reason": " ".join(reasons),
        }


# pylint: disable=invalid-name
_ROUTER = Router()
get_topics_list = _ROUTER.get_topics_list
get_answers = _ROUTER.get_answers
get_query_diagnostics = _ROUTER.get_query_diagnostics

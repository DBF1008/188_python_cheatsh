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

    def reset_cache(self):
        """Reset internal caches (topic types and topics list). Useful for tests."""
        self._cached_topics_list = []
        self._cached_topic_type = {}

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

    def diagnose(self, topic: str) -> Dict[str, Any]:
        """
        Trace the routing pipeline for `topic` without calling adapters.

        Returns a dict with:
            explicit_topic_type, effective_topic,
            is_random, random_resolved,
            routing_trace, topic_types, adapter_order,
            cache_info, resolution_reason
        """

        result = {
            "explicit_topic_type": "",
            "effective_topic": topic,
            "is_random": False,
            "random_resolved": "",
            "routing_trace": [],
            "topic_types": [],
            "adapter_order": [],
            "cache_info": [],
            "resolution_reason": "",
        }

        # 1. Strip explicit topic type prefix (e.g. "tldr:ls" -> type="tldr", topic="ls")
        if re.match("[^/]+:", topic):
            result["explicit_topic_type"], topic = topic.split(":", 1)

        # 2. Handle :random resolution
        resolved = self.handle_if_random_request(topic)
        if resolved != topic:
            result["is_random"] = True
            result["random_resolved"] = resolved
            topic = resolved

        result["effective_topic"] = topic

        # 3. Walk routing table, recording every entry
        trace = []
        matched_routes = []
        for regexp, route in self.routing_table:
            regex_matched = bool(re.search(regexp, topic))
            is_found_result = None
            if regex_matched:
                if route in self._adapter:
                    is_found_result = self._adapter[route].is_found(topic)
                    if is_found_result:
                        matched_routes.append(route)
                else:
                    # Adapter not instantiated — treat as matched unconditionally
                    is_found_result = None
                    matched_routes.append(route)

            trace.append({
                "regexp": regexp,
                "route": route,
                "regex_matched": regex_matched,
                "is_found": is_found_result,
            })

        result["routing_trace"] = trace

        # 4. Build topic_types list (same logic as get_topic_type)
        if not matched_routes:
            topic_types = [CONFIG["routing.default"]]
        elif len(matched_routes) > 1:
            topic_types = matched_routes[:-1]
        else:
            topic_types = matched_routes

        # 5. Apply explicit type filter
        explicit = result["explicit_topic_type"]
        if explicit and explicit in topic_types:
            topic_types = [explicit]

        result["topic_types"] = topic_types
        result["adapter_order"] = list(topic_types)

        # 6. Build cache_info for each adapter
        for topic_type in topic_types:
            if topic_type in self._adapter:
                cache_needed = self._adapter[topic_type].is_cache_needed()
            else:
                cache_needed = False

            if topic_type == "question":
                cache_key_pattern = "q:" + topic
            else:
                cache_key_pattern = "%s:%s" % (topic_type, topic)

            result["cache_info"].append({
                "adapter": topic_type,
                "cache_needed": cache_needed,
                "cache_key_pattern": cache_key_pattern,
            })

        # 7. Build resolution_reason
        if topic_types == ["unknown"]:
            result["resolution_reason"] = (
                "Single-word topic not found in any data adapter "
                "-> unknown (fuzzy suggestions)"
            )
        elif topic_types == ["question"]:
            result["resolution_reason"] = (
                "No routing rule matched any adapter "
                "-> default question adapter (StackOverflow)"
            )
        elif explicit and explicit not in matched_routes:
            result["resolution_reason"] = (
                "Explicit type '%s' requested but no adapter matched the topic "
                "-> type filter could not be satisfied" % explicit
            )
        else:
            result["resolution_reason"] = "Matched %d adapter(s): %s" % (
                len(topic_types), ", ".join(topic_types),
            )

        return result

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


# pylint: disable=invalid-name
_ROUTER = Router()
get_topics_list = _ROUTER.get_topics_list
get_answers = _ROUTER.get_answers

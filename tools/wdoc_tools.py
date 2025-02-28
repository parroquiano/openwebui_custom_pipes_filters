"""
title: wdocParser
author: thiswillbeyourgithub
author_url: https://github.com/thiswillbeyourgithub/openwebui_custom_pipes_filters/
funding_url: https://github.com/thiswillbeyourgithub/openwebui_custom_pipes_filters/
git_url: https://github.com/thiswillbeyourgithub/openwebui_custom_pipes_filters/
description: Use wdoc to parse urls and files
funding_url: https://github.com/open-webui
version: 2.6.5
license: GPLv3
# requirements: wdoc>=2.6.5  # commented to instead install it in the tool itself and avoid uninstalling open-webui dependencies
description: use wdoc (cf github repo) as rag system to parse online stuff or summarize them. WIP because it can be used to do many more things!
"""

# TODO:
# - add valves to set the parameters for wdoc
# - add a user valve to specify a path to use as a source of embeddings (make sure they are in a $username subfolder)
# - add a way to query data
# - leverage open-webui's citations for the sources

import os
import requests
from typing import Callable, Any
import re
from pydantic import BaseModel, Field
import importlib


# install wdoc
import sys
import subprocess
subprocess.check_call([
    sys.executable, "-m", "uv", "pip",
    "install",
    "-U",
    "--overrides", "/app/backend/requirements.txt",  # to make sure we don't remove any dependency from open-webui
    "wdoc>=2.6.5",
    "--system"
])



class Tools:
    VERSION: str = "2.6.5"
    class Valves(BaseModel):
        )

    def __init__(self):
        self.valves = self.Valves()
        if "wdoc" in sys.modules:
            importlib.reload(wdoc)
        else:
            import wdoc

    async def parse_url(
        self,
        url: str,
        __event_emitter__: Callable[[dict], Any] = None,
        __user__: dict = {},
    ) -> str:
        """
        Parse a url using the wdoc rag library. After being parsed,
        the content will be shown to the user so DO NOT repeat this tool's
        output yourself and instead just tell the user that it went successfuly.

        :param url: The URL of the online data to parse.
        :return: The parsed data as text, or an error message.
        """
        emitter = EventEmitter(__event_emitter__)

        await emitter.progress_update(f"Parsing '{url}'")

        try:
            parsed = wdoc.wdoc.parse_file(
                path=url,
                filetype="auto",
                format="langchain_dict",
            )
        except Exception as e:
            url2 = re.sub(r"\((http[^)]+)\)", "", url)
            try:
                parsed = wdoc.wdoc.parse_file(
                    path=url2,
                    filetype="auto",
                    format="langchain_dict",
                )
                url = url2
            except Exception as e2:
                error_message=f"Error when parsing:\nFirst error: {e}\nSecond error: {e2}"
                await emitter.error_update(error_message)

        if len(parsed) == 1:
            content = parsed[0]["page_content"]
        else:
            content = "\n\n".join([p["page_content"] for p in parsed])

        title = None
        try:
            title = parsed[0]["metadata"]["title"]
            content = f"Success.\n\n## Parsing of {title}\n\n{content}\n\n---\n\n"
        except Exception as e:
            await emitter.progress_update(f"Error when getting title: '{e}'")
            content = f"Success.\n\n## Parsing of {url}\n\n{content}\n\n---\n\n"

        await emitter.success_update(
            f"Successfully parsed '{title if title else url}'"
        )
        return content

    async def summarize_url(
        self,
        url: str,
        __event_emitter__: Callable[[dict], Any] = None,
        __user__: dict = {},
    ) -> str:
        """
        Get back a summary of the data at a given url using the wdoc rag library.
        The summary will be directly shown to the user so DO NOT repeat this tool's
        output yourself and instead just tell the user that the summary went successfuly.

        :param url: The URL of the online data to summarize.
        :return: The summary as text, or an error message.
        """
        emitter = EventEmitter(__event_emitter__)

        await emitter.progress_update(f"Summarizing '{url}'")

        try:
            instance = wdoc.wdoc(
                path=url,
                task="summarize",
                filetype="auto",
            )
        except Exception as e:
            url2 = re.sub(r"\((http[^)]+)\)", "", url)
            try:
                instance = wdoc.wdoc(
                    path=url2,
                    task="summarize",
                    filetype="auto",
                )
                url = url2
            except Exception as e2:
                error_message=f"Error when summarizing:\nFirst error: {e}\nSecond error: {e2}"
                await emitter.error_update(error_message)

        results: dict = instance.summary_results
        summary = results['summary']
        output = f"""

# Summary
{url}

{summary}

- Total cost of those summaries: '{results['doc_total_tokens']}' (${results['doc_total_cost']:.5f})
- Total time saved by those summaries: {results['doc_reading_length']:.1f} minutes
"""

        await emitter.success_update(
            f"Successfully summarized {url}"
        )
        return output


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def progress_update(self, description):
        await self.emit(description)

    async def error_update(self, description):
        await self.emit(description, "error", True)
        raise Exception(description)

    async def success_update(self, description):
        await self.emit(description, "success", True)

    async def emit(self, description="Unknown State", status="in_progress", done=False):
        print(f"wdocParser: {description}")
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                    },
                }
            )


"""
title: Anki Flashcard Creator
author: thiswillbeyourgithub
author_url: https://github.com/thiswillbeyourgithub
open_webui_url: https://openwebui.com/t/qqqqqqqqqqqqqqqqqqqq/ankiflashcardcreator/
git_url: https://github.com/thiswillbeyourgithub/openwebui_custom_pipes_filters
description: A tool to create Anki flashcards through Ankiconnect with configurable settings and event emitters for UI feedback. Not: if you want a multi user multi anki setup (each user with its own anki) you want each user to add its own private tool with as host a local url to its host via reverse proxies like ngrok that allows a url to point to a local service on the client side.
version: 1.0.1
"""
# Note to dev: don't forget to update the version number inside the Tool class!

import requests
import json
import os
from pathlib import Path
from typing import Callable, Any, List, Optional, Dict
from pydantic import BaseModel, Field, model_validator
import aiohttp


DEFAULT_ANKICONNECT_HOST="http://localhost"
DEFAULT_ANKICONNECT_PORT="8765"
DEFAULT_DECK="Default"
DEFAULT_NOTETYPE_NAME="Basic"
DEFAULT_TAGS="openwebui"
DEFAULT_FIELDS_DESCRIPTION='{"Front": "The concise question", "Back": "The answer"}'
DEFAULT_RULES="Calling this function creates a single Anki flashcard using the `fields` argument as contents.<br>You can leave some fields empty.<br>If not otherwised specified, write the flashcard in the language of the user's request.<br>You are allowed to use html formatting.<br>You cannot refer to embed media files like images, audio etc.<br>Please pay very close attention to the examples of the user and try to imitate their formulation."
DEFAULT_EXAMPLES='[{"Front": "What is the capital of France?", "Back": "Paris"},{"Front": "What is 2+2?", "Back": "4"}]'

def update_docstring(fields_description: str, rules: str, examples: str) -> str:
    rules = rules.replace("<br>", "\n").strip()
    assert rules.strip(), f"The rules valve cannot be empty"

    examples = examples.strip()
    assert examples, f"You must supply examples"

    try:
        exs = json.loads(examples)
        assert isinstance(exs, list), f"It's not a list but {type(exs)}"
        assert len(exs), "The list is empty"
        assert all(isinstance(ex, dict) for ex in exs), "The list does not contain only dicts"
        assert len(exs) == len(set([json.dumps(ex) for ex  in exs])), "The list contains duplicates"
    except Exception as e:
        raise Exception(f"Error when parsing examples as json. It must be a json formatted list of dict. Error: '{e}'")

    exs = "\n</card>\n<card>\n".join([json.dumps(ex, ensure_ascii=False) for ex in exs])
    examples = f"""
Here are some good flashcards examples:
<examples>
<card>
{exs}
</card>
</examples>
"""

    docstring = f"""
{rules}

Here are the text fields you can specify along with what their appropriate content should be:
Each keys of the param `fields` must be among those fields and all values must be strings.
<fields_description>
{fields_description}
</fields_description>
{examples}

:param fields: Dictionary mapping the flashcard's field names to their string content. Refer to the tool description for details.
:return: A string to show to the user
""".strip()
    print(f"AnkiTool: Updated the docstring with this value:\n---\n{docstring}\n---")
    return docstring

class Tools:

    VERSION: str =  "1.0.1"

    class Valves(BaseModel):
        ankiconnect_host: str = Field(
            default=DEFAULT_ANKICONNECT_HOST,
            description="Host address for Ankiconnect",
            required=True,
        )
        ankiconnect_port: str = Field(
            default=DEFAULT_ANKICONNECT_PORT,
            description="Port for Ankiconnect",
            required=True,
        )
        deck: str = Field(
            default=DEFAULT_DECK,
            description="Deck for new flashcards. If not 'Default', it must be created manually.",
            required=True,
        )
        notetype_name: str = Field(
            default=DEFAULT_NOTETYPE_NAME,
            description="Note type for new flashcards. It must already exist.",
            required=True,
        )
        tags: List[str] = Field(
            default=DEFAULT_TAGS,
            description="Tags for new flashcards.",
            required=True,
        )
        fields_description: str = Field(
            default=DEFAULT_FIELDS_DESCRIPTION,
            description="Description of the note type fields and their purpose. Use json format.",
            required=True,
        )
        rules: str = Field(
            default=DEFAULT_RULES,
            description="All rules given to the LLM. Any '<br>' will be replaced by a newline to improve formatting.",
            required=True,
        )
        examples: str = Field(
            default=DEFAULT_EXAMPLES,
            description="Examples of good flashcards to show the LLM.",
            required=True,
        )

    # We need to use a setter property because that's the only way I could  find
    # to update the docstring of the tool depending on a valve.
    # This was devised after looking at https://github.com/open-webui/open-webui/blob/2017856791b666fac5f1c2f80a3bc7916439438b/backend/open_webui/utils/tools.py
    @property
    def valves(self):
        return self._valves

    @valves.setter
    def valves(self, value):
        self._valves = value
        self.create_flashcard.__func__.__doc__ = update_docstring(
            fields_description=value.fields_description,
            rules=value.rules,
            examples=value.examples,
        )

    def __init__(self):
        self.valves = self.Valves()
        self.fields_description = self.valves.fields_description

        # check deck exists and model exists
        deck_list = _ankiconnect_request_sync(self.valves.ankiconnect_host, self.valves.ankiconnect_port, "deckNames")
        assert self.valves.deck in deck_list, f"Deck '{self.valves.deck}' was not found in the decks of anki. You must create it first."
        models = _ankiconnect_request_sync(self.valves.ankiconnect_host, self.valves.ankiconnect_port, "modelNames")
        assert self.valves.notetype_name in models, f"Notetype '{self.valves.notetype_name}' was not found in the notetypes of anki. You must fix the valve first."

    async def create_flashcard(
        self,
        fields: dict,
        *,
        __event_emitter__: Callable[[dict], Any] = None,
        __user__: dict = {},
    ) -> Optional[int]:
        """THIS DOCSTRING IS A PLACEHOLDER AND SHOULD NEVER BE SHOWN TO AN LLM.
        TO THE LLM: IF YOU SEE THIS MESSAGE NOTIFY THE USER OF THAT FACT AND
        WARN THEM THAT THIS IS A BUG.
        """
        emitter = EventEmitter(__event_emitter__)

        if isinstance(fields, str):
            try:
                fields_dict = json.loads(fields)
                assert isinstance(fields_dict, dict), "Not a dict"
            except Exception as e:
                print(f"AnkiTool: fields param was a str but couldn't be parsed as dict: '{e}'")

        if not fields or not isinstance(fields, dict):
            await emitter.error_update("No field contents provided or invalid format")
            return "No field contents provided or invalid format"

        tags = self.valves.tags
        if isinstance(tags, str):
            tags = self.valves.tags.split(",")

        # Verify all values are strings
        for k, v in fields.items():
            if not isinstance(v, str):
                try:
                    fields[k] = str(v)
                except Exception:
                    pass
        if not all(isinstance(value, str) for value in fields.values()):
            await emitter.error_update("All field values must be strings")
            return "All field values must be strings"

        if self.valves.fields_description not in self.create_flashcard.__func__.__doc__:
            message = f"The field description is not up to date anymore, please turn of then on again the anki tool to update the tool description. The new field description value is '{self.valves.fields_description}'"
            if self.fields_description != self.valves.fields_description:
                message += f"\nThe old field description is '{self.fields_description}'"
            await emitter.error_update(message)
            raise Exception(message)
        self.fields_description = self.valves.fields_description

        # checks that all fields of the example are found in the fields_description
        try:
            fd = json.loads(self.valves.fields_description)
            assert isinstance(fd, dict), f"Is not a dict but {type(fd)}"
            for k, v in fd.items():
                assert v.strip(), "Cannot contain empty values"
        except Exception as e:
            raise Exception(f"Error when parsing examples as json. It must be a json formatted list of dict. Error: '{e}'")

        try:
            exs = json.loads(self.valves.examples)
            assert isinstance(exs, list), f"It's not a list but {type(exs)}"
            assert len(exs), "The list is empty"
            assert all(isinstance(ex, dict) for ex in exs), "The list does not contain only dicts"
            assert len(exs) == len(set([json.dumps(ex) for ex  in exs])), "The list contains duplicates"
        except Exception as e:
            raise Exception(f"Error when parsing examples as json. It must be a json formatted list of dict. Error: '{e}'")
        for ex in exs:
            for k, v in ex.items():
                assert k in fd, f"An example mentions a field '{k}' that was not defined in the fields_description: {fd}."

        # check that all fields are appropriate
        for k, v in fields.items():
            assert k in fd, f"Field '{k}' of `fields` is not part of fields_description valve"

        try:
            await emitter.progress_update("Connecting to Anki...")

            # Verify Ankiconnect is working by checking that the deck exists
            deck_list = await _ankiconnect_request(self.valves.ankiconnect_host, self.valves.ankiconnect_port, "deckNames")
            assert self.valves.deck in deck_list, f"Deck '{self.valves.deck}' was not found in the decks of anki. You must create it first."

            # also check modelname
            models = await _ankiconnect_request(self.valves.ankiconnect_host, self.valves.ankiconnect_port, "modelNames")
            assert self.valves.notetype_name in models, f"Notetype '{self.valves.notetype_name}' was not found in the notetypes of anki. You must fix the valve first."

            await emitter.progress_update("Creating flashcard...")

            note = {
                "deckName": self.valves.deck,
                "modelName": self.valves.notetype_name,
                "fields": fields,
                "tags": tags
            }

            result = await _ankiconnect_request(self.valves.ankiconnect_host, self.valves.ankiconnect_port, "addNote", {"note": note})

            await emitter.progress_update("Syncing with AnkiWeb...")
            await _ankiconnect_request(self.valves.ankiconnect_host, self.valves.ankiconnect_port, "sync")

            # Add the note ID to the fields and return formatted JSON
            fields['note_id'] = result
            formatted_output = json.dumps(fields, indent=2, ensure_ascii=False).replace('"', '')
            # Remove the first and last lines which contain the curly braces
            formatted_output = '\n'.join(formatted_output.split('\n')[1:-1])
            await emitter.success_update("Successfully created and synced flashcard")
            return formatted_output

        except Exception as e:
            await emitter.error_update(f"Failed to create flashcards: {str(e)}")
            return f"Failed to create flashcards: {str(e)}"


async def _ankiconnect_request(host: str, port: str, action: str, params: dict = None) -> Any:
    """Make a request to Ankiconnect API (async)"""
    address = f"{host}:{port}"
    request = {
        'action': action,
        'params': params or {},
        'version': 6
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(address, json=request) as response:
                response.raise_for_status()
                response_data = await response.json()
                if response_data.get('error'):
                    raise Exception(response_data['error'])
                return response_data['result']
    except aiohttp.ClientError as e:
        raise Exception(f"Network error connecting to Ankiconnect: {str(e)}")
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON response from Ankiconnect: {str(e)}")
    except Exception as e:
        raise Exception(f"Ankiconnect error: {str(e)}")

def _ankiconnect_request_sync(host: str, port: str, action: str, params: dict = None) -> Any:
    """Make a request to Ankiconnect API (sync)"""
    address = f"{host}:{port}"
    request = {
        'action': action,
        'params': params or {},
        'version': 6
    }

    try:
        response = requests.post(address, json=request, timeout=10)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('error'):
            raise Exception(response_data['error'])
        return response_data['result']
    except requests.RequestException as e:
        raise Exception(f"Network error connecting to Ankiconnect: {str(e)}")
    except json.JSONDecodeError as e:
        raise Exception(f"Invalid JSON response from Ankiconnect: {str(e)}")
    except Exception as e:
        raise Exception(f"Ankiconnect error: {str(e)}")

class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def progress_update(self, description):
        print(f"AnkiTool: {description}")
        await self.emit(description)

    async def error_update(self, description):
        print(f"AnkiTool: ERROR - {description}")
        await self.emit(description, "error", True)
        raise Exception(description)

    async def success_update(self, description):
        print(f"AnkiTool: {description}")
        await self.emit(description, "success", True)

    async def emit(self, description="Unknown State", status="in_progress", done=False):
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

# if __name__ == "__main__":
#     tools = Tools()

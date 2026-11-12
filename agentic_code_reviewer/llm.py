"""Typed OpenAI response parsing with bounded retries for transient errors."""
import random
import time
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError
from .prompts import SYSTEM_POLICY


def get_client():
    # SDK retries disabled: our bounded retry loop is responsible for them.
    return OpenAI(max_retries=0, timeout=50.0)


def ask_typed(client, model: str, prompt: str, schema, max_attempts: int = 3):
    last_error = None
    for attempt in range(max_attempts):
        try:
            response = client.responses.parse(
                model=model,
                instructions=SYSTEM_POLICY,
                input=prompt,
                text_format=schema,
            )
            if response.output_parsed is None:
                raise ValueError("Model returned no parsed structured output (possible refusal/truncation)")
            usage = getattr(response, "usage", None)
            return response.output_parsed, {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            }
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            last_error = exc
        except APIStatusError as exc:
            if exc.status_code not in (408, 409, 429) and exc.status_code < 500:
                raise  # Do not retry bad API key, bad request, permission failure.
            last_error = exc
        except ValueError:
            raise  # Flag partial results rather than retrying structured refusals.
        if attempt < max_attempts - 1:
            time.sleep(min(8.0, (0.7 * (2 ** attempt)) + random.random() * 0.3))
    raise RuntimeError(f"OpenAI call failed after {max_attempts} attempts: {type(last_error).__name__}") from last_error

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PROMPT_CHARS = 48_000


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class StreamOptions(BaseModel):
    include_usage: bool = False


class ChatRequest(BaseModel):
    """The subset of OpenAI's chat completion request the gateway supports."""

    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1, max_length=100)
    messages: list[Message] = Field(min_length=1, max_length=100)
    temperature: float = Field(1.0, ge=0, le=2)
    top_p: float | None = Field(None, gt=0, le=1)
    max_tokens: int = Field(1024, ge=1, le=4096)
    stream: bool = False
    stream_options: StreamOptions | None = None

    @model_validator(mode="after")
    def _prompt_fits(self) -> Self:
        if self.prompt_chars() > MAX_PROMPT_CHARS:
            raise ValueError(f"messages are too long: at most {MAX_PROMPT_CHARS} characters in total")
        return self

    def prompt_chars(self) -> int:
        return sum(len(message.content) for message in self.messages)

    @property
    def include_usage(self) -> bool:
        return self.stream_options is not None and self.stream_options.include_usage

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PluginPermission(BaseModel):
    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)


class PluginRisk(BaseModel):
    network: bool = False
    shell: bool = False
    llm: bool = False
    destructive_data: bool = False


class PluginRequirements(BaseModel):
    core: str = ">=0.1,<0.2"
    plugins: list[str] = Field(default_factory=list)


class PluginProvides(BaseModel):
    pages: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    widgets: list[str] = Field(default_factory=list)


class PluginManifest(BaseModel):
    id: str
    name: str
    version: str
    level: int = Field(ge=1, le=4)
    description: str = ""
    default_enabled: bool = True
    requires: PluginRequirements = Field(default_factory=PluginRequirements)
    provides: PluginProvides = Field(default_factory=PluginProvides)
    subscribes: list[str] = Field(default_factory=list)
    permissions: PluginPermission = Field(default_factory=PluginPermission)
    risk: PluginRisk = Field(default_factory=PluginRisk)

    @field_validator("id")
    @classmethod
    def stable_id(cls, value: str) -> str:
        if not value or " " in value or value.lower() != value:
            raise ValueError("plugin id must be non-empty lowercase and contain no spaces")
        return value

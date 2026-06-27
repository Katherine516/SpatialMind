"""Backward-compatible import path for the structured agent loop."""

from .agent.loop import AgentResponse, SpatialAgent, ToolCall

__all__ = ["AgentResponse", "SpatialAgent", "ToolCall"]

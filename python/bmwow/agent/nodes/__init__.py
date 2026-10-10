"""One module per situation-analysis agent. Each exposes `async def run(ctx: AgentContext) -> None`."""

from . import baseline, competition, feedback, trends

AGENT_RUNS = {
    "baseline": baseline.run,
    "competition": competition.run,
    "feedback": feedback.run,
    "trends": trends.run,
}

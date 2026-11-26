"""Bounded Evolution control and provider outputs; never executable policy."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from .evolution_contract import DEFAULTS


Mode = Literal['generate', 'repair', 'optimize', 'expand', 'evolve']
Autonomy = Literal['manual', 'suggest', 'auto_build', 'assisted']
IDENTIFIER = r'^[a-z0-9][a-z0-9_-]{0,63}$'


class EvolutionModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EvolutionFlags(EvolutionModel):
    generate: StrictBool = False
    repair: StrictBool = False
    optimize: StrictBool = False
    expand: StrictBool = False
    evolve: StrictBool = False


class EvolutionLimits(EvolutionModel):
    budget_usd: float = Field(default=DEFAULTS['budget_usd'], gt=0, le=100, allow_inf_nan=False)
    max_builds: int = Field(default=DEFAULTS['max_builds'], ge=1, le=8, strict=True)
    max_generations_per_build: int = Field(default=DEFAULTS['max_generations_per_build'], ge=1, le=4, strict=True)
    daily_app_budget_usd: float = Field(default=DEFAULTS['daily_app_budget_usd'], gt=0, le=100, allow_inf_nan=False)
    mandate_ttl_days: int = Field(default=DEFAULTS['mandate_ttl_days'], ge=1, le=7, strict=True)
    output_tokens: dict[Literal['analysis','reflection','generate','review'],int] = Field(default_factory=lambda:dict(DEFAULTS['output_tokens']))

    @model_validator(mode='after')
    def token_bounds(self):
        if set(self.output_tokens)!={'analysis','reflection','generate','review'} or any(type(v) is not int or not 256<=v<=16000 for v in self.output_tokens.values()):
            raise ValueError('Invalid Evolution technical output limits')
        return self


class EvolutionConfig(EvolutionModel):
    enabled: StrictBool = False
    flags: EvolutionFlags = Field(default_factory=EvolutionFlags)
    autonomy: Autonomy = 'manual'
    telemetry_consent: StrictBool = False
    limits: EvolutionLimits = Field(default_factory=EvolutionLimits)
    user_preferences: list[str] = Field(default_factory=list,max_length=6)
    remove_user_preferences: list[str] = Field(default_factory=list,max_length=6)

    @model_validator(mode='after')
    def preference_bounds(self):
        if any(not s.strip() or len(s.encode('utf-8'))>240 for s in self.user_preferences):
            raise ValueError('Preferansen må være kort og fullstendig.')
        return self


class EvolutionPrepare(EvolutionModel):
    mode: Mode
    project_id: str = Field(pattern=IDENTIFIER)
    base_package_id: str | None = Field(default=None, pattern=IDENTIFIER)
    development_context_id: str | None = Field(default=None, pattern=IDENTIFIER)
    goal: str = Field(min_length=1, max_length=1000)
    autonomy: Autonomy | None = None
    limits: EvolutionLimits | None = None
    metric: str | None = Field(default=None, max_length=48)
    permissions: list[str] | None = Field(default=None,max_length=24)
    expected_revision: int = Field(default=0,ge=0,strict=True)


class EvolutionConfirm(EvolutionModel):
    proposal_id: str = Field(pattern=IDENTIFIER)
    expected_revision: int = Field(ge=0,strict=True)


class EvolutionControl(EvolutionModel):
    job_id: str | None = Field(default=None,pattern=IDENTIFIER)
    mandate_id: str | None = Field(default=None,pattern=IDENTIFIER)
    action: Literal['pause', 'stop', 'resume','revoke']
    expected_revision: int = Field(ge=0,strict=True)


class EvolutionFinding(EvolutionModel):
    category: Literal['source_defect', 'deployment', 'os_driver', 'missing_capability',
                      'ambiguous_timing', 'usability', 'optimization', 'expansion']
    summary: str = Field(min_length=1, max_length=320)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    requires_physical_test: bool


class EvolutionAnalysis(EvolutionModel):
    conclusion: str = Field(min_length=1, max_length=640)
    proposed_change: str = Field(max_length=1000)
    disposition: Literal['candidate', 'needs_physical', 'deployment_fix', 'not_actionable']
    findings: list[EvolutionFinding] = Field(default_factory=list, max_length=6)
    acceptance_checks: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def bounded_strings(self):
        if any(len(s.encode('utf-8')) > 320 for s in self.acceptance_checks):
            raise ValueError('Evolution acceptance check too long')
        if any(len(r.encode('utf-8')) > 160 for f in self.findings for r in f.evidence_refs):
            raise ValueError('Evolution evidence reference too long')
        return self


class EvolutionReflection(EvolutionModel):
    guidance: str = Field(max_length=2000)
    context_selection: list[str] = Field(default_factory=list, max_length=8)
    example_ids: list[str] = Field(default_factory=list, max_length=8)
    repair_method: str = Field(min_length=1, max_length=64)
    rationale: str = Field(max_length=640)

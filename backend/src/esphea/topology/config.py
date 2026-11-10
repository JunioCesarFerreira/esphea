"""Configuration of the analyses of a run, discriminated by ``kind``."""

from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

from esphea.topology.clouds import NormalizationKind, PointCloudKind
from esphea.topology.zigzag import MiddleComplex

TOPOLOGY_ANALYSIS = "topology"
ZIGZAG_ANALYSIS = "zigzag"
MAX_POINTS = 2000
"""Largest point cloud accepted for Vietoris-Rips (cost grows quickly with size)."""
MAX_EPSILONS = 5
_STORED = "stored"
"""Validation context flag of a configuration read back from the database."""


class TopologyAnalysisConfig(BaseModel):
    """Vietoris-Rips persistence of every stored generation, and distances between them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["topology"] = "topology"
    point_cloud: PointCloudKind = Field(
        default=PointCloudKind.SURVIVORS,
        description="Which individuals of each stored generation form the point cloud.",
    )
    normalization: NormalizationKind = Field(
        default=NormalizationKind.NONE,
        description="Scaling of the objective space before computing distances.",
    )
    max_dimension: int = Field(default=1, ge=0, le=2, description="Highest homology dimension.")
    max_epsilon: float = Field(
        gt=0,
        le=1e6,
        description="Largest edge length of the Vietoris-Rips filtration (scale 0..max_epsilon).",
    )
    distance_matrix: bool = Field(
        default=False,
        description="Also compute distances between all pairs of (up to 100) generations.",
    )


class ZigzagAnalysisConfig(BaseModel):
    """Zigzag persistence of P_{t-1} -> R_t <- P_t at fixed Vietoris-Rips scales."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["zigzag"] = "zigzag"
    epsilons: tuple[float, ...] = Field(
        min_length=1,
        max_length=MAX_EPSILONS,
        description="Fixed scales (edge lengths); one zigzag barcode per scale.",
    )
    max_dimension: int = Field(default=0, ge=0, le=2, description="Highest homology dimension.")
    normalization: NormalizationKind = Field(
        default=NormalizationKind.NONE,
        description=(
            "'none' or 'ideal_nadir' (a per-generation scaling would break the inclusions)."
        ),
    )
    middle: MiddleComplex = Field(
        default=MiddleComplex.RIPS,
        description=(
            "Complex at every R_t: 'rips' (Vietoris-Rips of all candidates: what each "
            "generation builds and destroys) or 'union' (Vietoris-Rips of the parents and the "
            "survivors, leaving out the offspring discarded at once: the features of the "
            "populations, followed through the induced maps). 'bridge' and 'bridge_union' are "
            "retired and only appear in stored analyses."
        ),
    )
    representatives: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Longest bars per dimension and scale whose representative cycles are kept.",
    )

    @field_validator("middle")
    @classmethod
    def _current_middle(cls, middle: MiddleComplex, info: ValidationInfo) -> MiddleComplex:
        if middle.retired and not (info.context or {}).get(_STORED):
            raise ValueError(f"the '{middle}' complex was retired; use 'rips' or 'union'")
        return middle

    @model_validator(mode="after")
    def _check(self) -> Self:
        if any(eps <= 0 for eps in self.epsilons):
            raise ValueError("every epsilon must be positive")
        if len(set(self.epsilons)) != len(self.epsilons):
            raise ValueError("epsilons must be distinct")
        if self.normalization == NormalizationKind.MIN_MAX:
            raise ValueError(
                "per-generation min-max normalisation breaks the zigzag inclusions; "
                "use 'none' or 'ideal_nadir'"
            )
        object.__setattr__(self, "epsilons", tuple(sorted(self.epsilons)))
        return self


AnalysisConfig = Annotated[
    TopologyAnalysisConfig | ZigzagAnalysisConfig, Field(discriminator="kind")
]
_ANALYSIS_CONFIG: TypeAdapter[TopologyAnalysisConfig | ZigzagAnalysisConfig] = TypeAdapter(
    AnalysisConfig
)


def parse_analysis_config(
    kind: str, data: dict[str, Any]
) -> TopologyAnalysisConfig | ZigzagAnalysisConfig:
    """Rebuild a stored configuration (rows keep ``kind`` in their own column).

    Retired settings are accepted here, so that the analyses stored with them still load.
    """
    return _ANALYSIS_CONFIG.validate_python({**data, "kind": kind}, context={_STORED: True})

"""Configuration of the analyses of a run, discriminated by ``kind``."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from esphea.topology.clouds import NormalizationKind, PointCloudKind
from esphea.topology.zigzag import MiddleComplex

TOPOLOGY_ANALYSIS = "topology"
ZIGZAG_ANALYSIS = "zigzag"
MAX_POINTS = 2000
"""Largest point cloud accepted for Vietoris-Rips (cost grows quickly with size)."""
MAX_EPSILONS = 5


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
            "Complex at every R_t: 'rips' (Vietoris-Rips of all candidates) or "
            "'bridge_union', the bridge complex VR(P_{t-1} + P_t) joined by a spanning forest "
            "of the other edges of R_t: the same H0 barcode, and the H1/H2 of the union zigzag, "
            "without the holes opened or filled by discarded offspring alone."
        ),
    )
    representatives: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Longest bars per dimension and scale whose representative cycles are kept.",
    )

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
    """Rebuild a stored configuration (rows keep ``kind`` in their own column)."""
    return _ANALYSIS_CONFIG.validate_python({**data, "kind": kind})

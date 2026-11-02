"""Configuration of a persistent-homology analysis of a run."""

from pydantic import BaseModel, ConfigDict, Field

from esphea.topology.clouds import NormalizationKind, PointCloudKind

TOPOLOGY_ANALYSIS = "topology"
MAX_POINTS = 2000
"""Largest point cloud accepted for Vietoris-Rips (cost grows quickly with size)."""


class TopologyAnalysisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

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

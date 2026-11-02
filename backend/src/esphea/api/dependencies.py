"""FastAPI dependency providers."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from esphea.api.infrastructure import Infrastructure
from esphea.services.analyses import AnalysisService
from esphea.services.experiments import ExperimentService
from esphea.services.results import ResultsService


def get_infrastructure(connection: HTTPConnection) -> Infrastructure:
    infrastructure: Infrastructure = connection.app.state.infrastructure
    return infrastructure


InfrastructureDep = Annotated[Infrastructure, Depends(get_infrastructure)]


def get_session(infrastructure: InfrastructureDep) -> Iterator[Session]:
    with infrastructure.sessions() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_experiment_service(
    session: SessionDep, infrastructure: InfrastructureDep
) -> ExperimentService:
    return ExperimentService(
        session,
        queue=infrastructure.queue,
        cancellation=infrastructure.cancellation,
        publisher=infrastructure.publisher,
        runs_dir=infrastructure.runs_dir,
    )


def get_results_service(session: SessionDep, infrastructure: InfrastructureDep) -> ResultsService:
    return ResultsService(
        session, problems=infrastructure.problems, runs_dir=infrastructure.runs_dir
    )


def get_analysis_service(session: SessionDep, infrastructure: InfrastructureDep) -> AnalysisService:
    return AnalysisService(
        session,
        queue=infrastructure.queue,
        problems=infrastructure.problems,
        runs_dir=infrastructure.runs_dir,
    )


ExperimentServiceDep = Annotated[ExperimentService, Depends(get_experiment_service)]
AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]
ResultsServiceDep = Annotated[ResultsService, Depends(get_results_service)]

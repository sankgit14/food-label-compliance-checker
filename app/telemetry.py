"""OpenTelemetry setup shared by the API, agent worker, and tool calls."""

import os
from functools import lru_cache

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@lru_cache(maxsize=4)
def configure_tracing(service_name: str) -> TracerProvider:
    """Create a provider and export spans when an OTLP endpoint is configured."""
    current = trace.get_tracer_provider()
    if current.__class__.__name__ != "ProxyTracerProvider":
        # A test process may host the API and worker together; production runs
        # configure each service in its own process.
        return current
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
    trace.set_tracer_provider(provider)
    return provider


def instrument_fastapi(app) -> None:
    """Add route spans if the app instrumentation dependency is installed."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=configure_tracing("food-label-api"),
    )

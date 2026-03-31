# ── Build stage ────────────────────────────────────────────────────────────────
FROM rust:bookworm AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        cmake \
        clang \
        libclang-dev \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY . .

RUN cargo build --release --bin cli

# ── Runtime stage ───────────────────────────────────────────────────────────────
FROM debian:bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /paddle
COPY --from=builder /build/target/release/cli /paddle/cli
COPY --from=builder /build/models /paddle/models

CMD ["tail", "-f", "/dev/null"]

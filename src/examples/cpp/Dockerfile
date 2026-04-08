ARG RELEASE
ARG LAUNCHPAD_BUILD_ARCH
FROM ubuntu:${RELEASE:-22.04}

LABEL org.opencontainers.image.ref.name=ubuntu
LABEL org.opencontainers.image.version=22.04

ENV DEBIAN_FRONTEND=noninteractive
USER root

# Install tools (tini for entrypoint, g++ to build the example)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates build-essential g++ tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

# Copy the example source (assumes simple_counter.cpp is next to this Dockerfile)
COPY simple_counter.cpp /tmp/program.cpp

# Compile the program and make it executable
RUN g++ /tmp/program.cpp -O2 -o /usr/local/bin/simple_counter && \
    chmod +x /usr/local/bin/simple_counter

# Create any needed directories
RUN mkdir -p /tmp/checkpoints /script-data

VOLUME ["/tmp/checkpoints","/script-data"]

# Use tini as entrypoint and run the compiled program by default
ENTRYPOINT ["/usr/bin/tini", "--"]
# CMD ["/usr/local/bin/simple_counter"]

FROM eclipse-temurin:21-jre-jammy

ARG BURP_VERSION=2026.10.1
ARG BURP_SHA256=e8ab086537b1643b91ca09d2fc2a6c3e08a8bae0c85280797c5c9ec76506c3c5
ARG REBURP_VERSION=1.1.15
ARG REBURP_SHA256=0290f63303839331391c06a8e07008dff0d6a61e78a6c26d7e1c320ebf149054

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/burp \
    && curl --fail --location --retry 3 --output /opt/burp/burp.jar \
        "https://portswigger.net/burp/releases/download?product=desktop&version=${BURP_VERSION}&type=Jar" \
    && echo "${BURP_SHA256}  /opt/burp/burp.jar" | sha256sum --check \
    && curl --fail --location --retry 3 --output /opt/burp/reburp.jar \
        "https://github.com/forefy/reburp/releases/download/v${REBURP_VERSION}/reburp-${REBURP_VERSION}.jar" \
    && echo "${REBURP_SHA256}  /opt/burp/reburp.jar" | sha256sum --check

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxi6 libxrender1 libxtst6 xdotool \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 burp

COPY --chown=burp:burp user-options.json /opt/burp/user-options.json
COPY --chown=burp:burp start.sh /opt/burp/start.sh

USER burp
WORKDIR /home/burp

ENTRYPOINT ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24", "sh", "/opt/burp/start.sh"]

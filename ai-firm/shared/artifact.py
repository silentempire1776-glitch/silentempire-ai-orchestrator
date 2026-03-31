# --------------------------------------------------
# ARTIFACT BUILDER
# --------------------------------------------------

def build_artifact(artifact_type, version, data):
    return {
        "artifact_type": artifact_type,
        "version": version,
        "data": data
    }

# --------------------------------------------------
# ARTIFACT EXTRACTOR
# --------------------------------------------------

def extract_artifact(envelope):
    return envelope.get("payload", {}).get("artifact")

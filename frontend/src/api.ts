import type { TransformationRequest } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super("The request could not be completed.");
    this.name = "ApiError";
  }
}

async function requestJson(
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
  });
  let body: unknown = null;
  if (response.status !== 204) {
    try {
      body = await response.json();
    } catch {
      body = null;
    }
  }
  if (!response.ok) throw new ApiError(response.status, body);
  return body;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export const api = {
  session: () => requestJson("/api/auth/session"),
  authConfig: () => requestJson("/api/auth/config"),
  login: (username: string, password: string, registering: boolean) =>
    requestJson(
      "/api/auth/" + (registering ? "register" : "login"),
      jsonInit("POST", { username, password }),
    ),
  logout: () => requestJson("/api/auth/logout", { method: "POST" }),
  transformations: () => requestJson("/api/transformations"),
  sourceVersion: (id: number) => requestJson("/api/source-versions/" + id),
  transformation: (id: number) => requestJson("/api/transformations/" + id),
  revisionImpact: (id: number) =>
    requestJson("/api/transformations/" + id + "/revision-impact"),
  extractTextFile: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return requestJson("/api/sources/text-file", {
      method: "POST",
      body: formData,
    });
  },
  createTransformation: (request: TransformationRequest) =>
    requestJson("/api/transformations", jsonInit("POST", request)),
  generate: (transformationId: number) =>
    requestJson("/api/transformations/" + transformationId + "/generate", {
      method: "POST",
    }),
  retryArtifact: (artifactRunId: number) =>
    requestJson("/api/artifact-runs/" + artifactRunId + "/retry", {
      method: "POST",
    }),
  saveArtifactVersion: (artifactRunId: number, content: string) =>
    requestJson(
      "/api/artifact-runs/" + artifactRunId + "/versions",
      jsonInit("POST", { content }),
    ),
  regenerateArtifact: (artifactRunId: number) =>
    requestJson("/api/artifact-runs/" + artifactRunId + "/regenerate", {
      method: "POST",
    }),
  targetedUpdate: (artifactRunId: number) =>
    requestJson("/api/artifact-runs/" + artifactRunId + "/targeted-update", {
      method: "POST",
    }),
  saveSourceVersion: (transformationId: number, sourceText: string) =>
    requestJson(
      "/api/transformations/" + transformationId + "/source-versions",
      jsonInit("POST", { source_text: sourceText }),
    ),
  reviewArtifact: (
    artifactVersionId: number,
    reviewStatus: "accepted" | "rejected",
  ) =>
    requestJson(
      "/api/artifact-versions/" + artifactVersionId + "/review",
      jsonInit("PATCH", { review_status: reviewStatus }),
    ),
  evidence: (artifactVersionId: number) =>
    requestJson("/api/artifact-versions/" + artifactVersionId + "/evidence"),
  analyzeEvidence: (versionId: number, sourceVersionId: number) =>
    requestJson(
      "/api/artifact-versions/" + versionId + "/evidence/analyze",
      jsonInit("POST", { source_version_id: sourceVersionId }),
    ),
  analyzeDiscrepancy: (versionAId: number, versionBId: number) =>
    requestJson(
      "/api/discrepancies/analyze",
      jsonInit("POST", {
        artifact_version_a_id: versionAId,
        artifact_version_b_id: versionBId,
      }),
    ),
  dismissDiscrepancy: (findingId: number) =>
    requestJson(
      "/api/discrepancies/" + findingId,
      jsonInit("PATCH", { review_status: "dismissed" }),
    ),
};

# AgentCore Deployment Scaffold

Future bridge for wrapping the BFSI Research Agent into an **Amazon Bedrock AgentCore** agent.

This scaffold does **not** deploy automatically. It provides guidance and artifacts for a future migration.

---

## Overview

The BFSI Research Agent can be wrapped as an AgentCore runtime that:

- Accepts prompts (question + PDF path or document reference)
- Runs the existing orchestrator pipeline
- Returns answer, provenance, and confidence

AgentCore provides:

- Managed runtime lifecycle
- Session management
- Optional memory (STM/LTM)
- OAuth/JWT authentication
- VPC networking for private resources

---

## AgentCore Create Commands

### 1. Install AgentCore CLI

```bash
pip install bedrock-agentcore-starter-toolkit
```

### 2. Configure Agent

```bash
agentcore configure \
  --entrypoint agent_entrypoint.py \
  --name bfsi-research-agent \
  --disable-memory \
  --non-interactive
```

Or with memory:

```bash
agentcore configure \
  --entrypoint agent_entrypoint.py \
  --name bfsi-research-agent \
  --non-interactive
```

### 3. Deploy

```bash
agentcore deploy
```

### 4. Invoke

```bash
agentcore invoke '{"prompt": "What is the CET1 ratio in this report?", "pdf_path": "s3://bucket/report.pdf"}'
```

---

## Minimal IAM Policy

The execution role for the AgentCore runtime needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:*:inference-profile/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::YOUR-BUCKET/*"
    }
  ]
}
```

Adjust `YOUR-BUCKET` for PDF storage. Add Secrets Manager access if credentials are stored there.

---

## Architecture Notes

### Entrypoint Adapter

Create `agent_entrypoint.py` that:

1. Receives `payload` with `prompt` and optional `pdf_path` / `document_ref`
2. Calls `orchestrator.run_workflow(prompt, pdf_path, use_streaming=False)`
3. Returns `{answer, confidence, provenance}` in the expected AgentCore format

### PDF Access

- **Option A**: PDFs in S3; pass `s3://bucket/key` as `pdf_path`; ensure runtime role has `s3:GetObject`.
- **Option B**: Pre-load documents into AgentCore memory or a document store; reference by ID.

### External Tools

- Tool credentials should come from Secrets Manager or Parameter Store, not local files.
- Update `tools.py` to read from `boto3.client("secretsmanager")` when running in AgentCore.

### Memory

- AgentCore STM/LTM can complement or replace per-PDF JSON memory.
- Map `session_id` / `actor_id` to PDF or document context for multi-tenant use.

---

## No Auto-Deploy

This scaffold is documentation only. Run `agentcore configure` and `agentcore deploy` manually when ready.

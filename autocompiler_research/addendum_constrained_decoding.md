# Addendum: Schema & Grammar-Constrained Decoding Integration in JanusMaskJR

This document serves as an implementation addendum to [academic_harness_distillation_research.md](file:///home/xnihil0zer0/JanusMaskJR/academic_harness_distillation_research.md) and [auto_compiler_adversarial_critique.md](file:///home/xnihil0zer0/JanusMaskJR/auto_compiler_adversarial_critique.md). It verifies the feasibility, evaluates cost-benefit trade-offs, details API schema specifications, and structures the exception handling patterns required to integrate constrained decoding within the JanusMaskJR verification loop.

---

## 1. Adversarial Critique: Trade-Off & Overhead Analysis

### A. Remote Gemini API: Structured JSON (`response_schema`) vs. Raw Text

Enforcing JSON schema validation at the Gemini API boundary via the `response_schema` configuration offers structural guarantees but introduces several latency, cost, and qualitative bottlenecks.

1. **Prefill Latency (Schema Compilation Overhead):**
   When a request specifies a `response_schema`, the Gemini API gateway must compile the JSON schema constraints into a logit-bias state machine or context-free grammar constraints. This compilation overhead adds **150ms to 400ms of prefill latency (Time to First Token)** per API call, depending on schema size and nesting depth.

2. **Output Token Overhead and Cost Inflation:**
   Constrained JSON decoding requires the model to output syntax formatting tokens—such as keys, quotes, colons, brackets, and indentation whitespace. For a list of multiple code edits, these structural tokens can account for up to **40% of the total output tokens**. Because Gemini API calls are billed per token, and token generation speed is bound by the serial decoding rate, using a verbose JSON schema directly increases costs and generation times compared to raw text.

3. **Reasoning Quality Degradation:**
   Forcing an autoregressive transformer to immediately fit its first tokens into a strict JSON syntax limits its capacity for intermediate planning. When the model cannot output free-form chain-of-thought tokens before generating edits, its accuracy on complex logic tasks drops. To prevent this, any `response_schema` must include a `"reasoning"` or `"thought"` field at the beginning of the schema, allowing the model to perform spatial planning before outputting the structured code chunks.

4. **Token Cutoff Hazards (Truncation):**
   If generation hits the output token limit (`finish_reason == "MAX_TOKENS"`), the payload terminates mid-stream. An unconstrained raw text block is often recoverable (as individual files or lines remain complete), but a truncated JSON document is fundamentally corrupt and will throw standard parser exceptions. This necessitates partial parsing or repair engines.

### B. Local Gemma Constrained Decoding (e.g., via Outlines)

Using local frameworks like Outlines to enforce context-free grammars (CFG) or regex constraints on local Gemma models shifts the computational bottleneck directly to local CPU and GPU environments.

1. **FSM Compilation Costs for Large Vocabularies:**
   Outlines maps schema/regex structures to the model's vocabulary during initialization. The Gemma 2 tokenizer contains **256,000+ tokens**. Compiling a Finite State Machine (FSM) over a 256k-dimensional vocabulary takes significant CPU processing power and memory (system RAM). A complex JSON schema FSM compilation can take **2 to 8 seconds**, blocking the execution pipeline.

2. **Logit Masking and PCIe Bottlenecks:**
   To enforce constraints during sampling, Outlines determines the subset of valid tokens at each step, maps them to token IDs, and constructs a boolean mask (size 256k). 
   * **GPU Masking Overhead:** Storing and computing vocabulary mappings consumes VRAM.
   * **PCIe Bus Latency:** If the logits are copied from GPU to CPU to apply the FSM mask and then copied back to GPU for sampling, the PCIe transfer bottleneck slows down token generation by **2x to 5x** compared to unconstrained local inference.

3. **Logit Scarcity & Probabilistic Deadlocks:**
   If the grammar constraint forces the model away from its high-probability path, the remaining valid tokens may have near-zero model probability. This logit scarcity leads to a probability sink where the model is forced to sample low-probability tokens. Under low temperature, this causes repetitive loops (e.g., spaces or empty strings) or deadlocks the generation process.

---

## 2. Implementation & Schema Configuration Details

### A. Configuring the Gemini SDK `response_schema`

The Python `google-genai` and `google-generativeai` SDKs accept Pydantic models directly, converting them to schema definitions.

For integration into [run_chat_turn](file:///home/xnihil0zer0/JanusMaskJR/overseer/turn_runner.py#L254) or [run_turn](file:///home/xnihil0zer0/JanusMaskJR/overseer/driver.py#L127), the schema is declared using Pydantic:

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class ASTEditBlock(BaseModel):
    file_path: str = Field(
        description="The absolute path of the target file to modify. Must be located under the project repository root."
    )
    start_line: int = Field(
        gt=0,
        description="The 1-indexed starting line number of the target block to replace."
    )
    end_line: int = Field(
        gt=0,
        description="The 1-indexed ending line number of the target block (inclusive)."
    )
    target_content: str = Field(
        description="The exact text content inside the target line range. Must match whitespace and characters precisely."
    )
    replacement_content: str = Field(
        description="The replacement source code to be spliced into the file in place of target_content."
    )

class ASTRefactoringPayload(BaseModel):
    reasoning: str = Field(
        description="A detailed explanation of the plan, justifying why these edits resolve the issue safely."
    )
    edits: List[ASTEditBlock] = Field(
        description="A sequence of non-contiguous AST patches to apply to the repository."
    )
```

The schema is registered in the API call config as follows:

```python
from google import genai
from google.genai import types

def generate_constrained_edits(client: genai.Client, prompt: str) -> ASTRefactoringPayload:
    # Configure the generation parameters
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ASTRefactoringPayload,
        temperature=0.1,  # Low temperature minimizes structural drift
        max_output_tokens=4096
    )
    
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config=config
    )
    
    # Parse the returned string into the Pydantic model
    return ASTRefactoringPayload.model_validate_json(response.text)
```

### B. JSON Schema for AST Diff Edits

Below is the raw JSON schema format aligned with the Pydantic schema, to be used for API configurations or local validation:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ASTRefactoringPayload",
  "type": "object",
  "properties": {
    "reasoning": {
      "type": "string",
      "description": "Planning and reasoning steps explaining the structural changes."
    },
    "edits": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "file_path": {
            "type": "string",
            "description": "Absolute path to the target source file."
          },
          "start_line": {
            "type": "integer",
            "minimum": 1,
            "description": "1-indexed starting line number."
          },
          "end_line": {
            "type": "integer",
            "minimum": 1,
            "description": "1-indexed ending line number."
          },
          "target_content": {
            "type": "string",
            "description": "Exact target content inside the file including line breaks."
          },
          "replacement_content": {
            "type": "string",
            "description": "Replacement source code block."
          }
        },
        "required": ["file_path", "start_line", "end_line", "target_content", "replacement_content"],
        "additionalProperties": false
      }
    }
  },
  "required": ["reasoning", "edits"],
  "additionalProperties": false
}
```

#### Key Formatting Constraints:
1. **No Line Number Drift:** Edits inside a single file must be ordered in **descending order of starting lines** (bottom-up edit application). Applying edits from the bottom up ensures that line offsets for subsequent modifications remain unchanged.
2. **Whitespace Parity:** Standardized AST comparisons are performed using the [_ValidationVisitor](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py#L25) to ignore irrelevant spacing while verifying structural logic.

### C. Parser Exception Handling & Truncation Recovery

If the model run is cut off or fails due to probability sinks, the parser must react gracefully instead of crashing the worker daemon.

#### Truncation Recovery Strategy (API MAX_TOKENS)
When Gemini hits the token limit, the JSON output is truncated. Rather than throwing a `JSONDecodeError`, the parser should employ a regex-based or token-based reconstruction mechanism (or use a helper library like `json-repair`):

```python
import json
import logging
from typing import Dict, Any

logger = logging.getLogger("janusmask.parser")

def parse_truncated_response(raw_text: str) -> Dict[str, Any]:
    """Parse JSON that might be truncated, attempting to recover completed objects."""
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        # Import json-repair if available, otherwise apply a fallback recovery
        try:
            from json_repair import repair_json
            repaired_text = repair_json(raw_text)
            parsed = json.loads(repaired_text)
            
            # Post-processing: remove incomplete items in the 'edits' list
            if isinstance(parsed, dict) and "edits" in parsed:
                valid_edits = []
                required_keys = {"file_path", "start_line", "end_line", "target_content", "replacement_content"}
                for edit in parsed["edits"]:
                    if isinstance(edit, dict) and required_keys.issubset(edit.keys()):
                        valid_edits.append(edit)
                parsed["edits"] = valid_edits
            return parsed
        except Exception as e:
            logger.error(f"Failed to repair truncated JSON: {e}")
            raise
```

#### Outlines Logit Collapse / Deadlock Prevention
If the grammar blocks the model's preferred tokens, local constrained decoding runs the risk of generating infinite spaces or getting stuck.
To resolve this:
1. **Wall-clock timeout wrappers:** Standardize timeouts around model queries to guarantee release of the process namespace.
2. **Logit Probability Monitoring:** Hook into the sampling step. If the cumulative probability of valid (masked) tokens drops below a threshold (e.g., $P < 0.01$ over 3 consecutive steps), abort the run immediately with a `ConstrainedDecodingException` and fall back to a standard chat generation with post-hoc AST enforcement.

---

## 3. Integration Plan in JanusMaskJR

To roll out constrained decoding:

1. **Extend Settings Schema:**
   Modify [config/gemini_settings.json](file:///home/xnihil0zer0/JanusMaskJR/config/gemini_settings.json) to support `response_schema` options for semantic edit tools.
2. **Update Stream Parser:**
   In [GeminiStreamParser](file:///home/xnihil0zer0/JanusMaskJR/harness/agent_streamer.py#L240), add JSON chunk accumulation and streaming JSON repair capabilities to dynamically display partial structured output in the operator log.
3. **Guard Code Merges:**
   Run checks on the generated payload using [ast_enforcer.py](file:///home/xnihil0zer0/JanusMaskJR/harness/ast_enforcer.py) before the edits are merged into git branches using [check_wired](file:///home/xnihil0zer0/JanusMaskJR/harness/wire_up.py#L305).

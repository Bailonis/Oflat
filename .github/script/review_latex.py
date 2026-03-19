import os
import re
from pathlib import Path

from openai import OpenAI

# Initialize Groq client
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.environ.get("GROQ_API_KEY")
)

def get_git_diff():
    # Gets the diff for .tex files in Chapters/ between the PR branch and the target branch
    import subprocess
    base = os.environ.get("BASE_REF")
    cmd = ["git", "diff", f"origin/{base}...HEAD", "--", "Chapters/*.tex"]
    diff = subprocess.check_output(cmd).decode("utf-8")
    return diff

MAX_DIFF_CHARS = 20_000  # ~10k tokens; enough for most PRs without blowing the context window

def parse_diff(raw_diff):
    """Convert a raw unified git diff into a structured, LLM-readable format
    that clearly labels each changed line with its file name and line number."""
    lines = raw_diff.splitlines()
    output = []
    current_file = None
    old_line = 0
    new_line = 0

    for line in lines:
        if line.startswith("diff --git "):
            parts = line.split(" b/")
            current_file = parts[-1] if len(parts) > 1 else "unknown"
            output.append(f"\n### File: {current_file}")
        elif line.startswith("--- ") or line.startswith("+++ "):
            continue  # file names already captured above
        elif line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(2))
                output.append(f"\n  [Hunk — old starts L{old_line}, new starts L{new_line}]")
        elif line.startswith("+"):
            output.append(f"  [L{new_line:4d} ADDED]   {line[1:]}")
            new_line += 1
        elif line.startswith("-"):
            output.append(f"  [L{old_line:4d} REMOVED] {line[1:]}")
            old_line += 1
        else:
            # context line — include so the LLM can see the surrounding paragraph
            output.append(f"  [L{new_line:4d} CONTEXT] {line}")
            old_line += 1
            new_line += 1

    structured = "\n".join(output)
    if len(structured) > MAX_DIFF_CHARS:
        structured = structured[:MAX_DIFF_CHARS] + "\n\n[... diff truncated: exceeds review limit ...]"
    return structured


def get_groq_review(diff_text):
    prompt = f"""
    You are an expert academic editor and computer science reviewer specializing in formal methods, \
theory of computation, and programming language theory. You are reviewing a master's dissertation \
written in LaTeX.

    ## Thesis Context
    The dissertation is titled around the development of pedagogical tools for Formal Languages and \
Automata Theory (FLAT) at FCT-UNL (Universidade Nova de Lisboa). Specifically:
    - It extends the **OCamlFLAT** library (an OCaml-based library for FLAT concepts) with support \
for **attribute grammars**.
    - It enhances the **OFLAT** graphical web application with interactive visualizations for \
attribute grammars.
    - It covers theoretical foundations of Theory of Computation (automata, formal grammars, \
attribute grammars), surveys existing FLAT educational software, and presents the current state \
of OCamlFLAT/OFLAT.
    - A key focus is **pedagogical quality** — the software and text must be clear and accessible \
to students learning these concepts for the first time.

    ## Your Review Tasks
    Review the following LaTeX git diff (only lines starting with '+' are new/changed content) and provide:

    1. **Grammar & Spelling**: Identify and correct grammatical errors, typos, awkward phrasing, \
and non-native English constructions.
    2. **Clarity & Readability**: Flag sentences that are overly complex, ambiguous, or hard to \
follow. Suggest clearer rewrites.
    3. **Academic Tone & Style**: Ensure the writing is formal, precise, and consistent with \
academic dissertation standards (e.g., avoid informal language, first-person where inappropriate, \
vague claims).
    4. **Technical Accuracy & Terminology**: Check that domain-specific terms (e.g., attribute \
grammars, synthesized/inherited attributes, automata, formal languages) are used correctly and \
consistently.
    5. **Pedagogical Clarity**: Since this is a pedagogical dissertation, flag any explanations of \
concepts that could be made more accessible or better structured for a student audience.
    6. **Structure & Flow**: Comment on transitions between ideas, paragraph cohesion, and whether \
the logical progression of arguments is clear.

    ## Output Format
    - Use Markdown with clear section headers matching the tasks above.
    - Use bullet points for individual issues.
    - For each issue, quote or reference the problematic text and provide a concrete suggestion.
    - Be concise but specific. Prioritize the most impactful improvements.
    - If a section has no issues, you may skip it.

    ## Diff Content
    The diff below has been pre-processed into a structured format for readability:
    - Each changed file is introduced with a `### File:` header.
    - Added lines are labelled `[L<number> ADDED]` — **these are the lines to review**.
    - Removed lines are labelled `[L<number> REMOVED]` — provided for context only.
    - Hunk markers show where in the file each group of changes appears.

    {diff_text}
    """

    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="openai/gpt-oss-120b",
    )
    return chat_completion.choices[0].message.content

def write_feedback(feedback):
    Path("feedback.md").write_text(
        "### 🤖 Groq AI Review for Chapters/\n\n" + feedback,
        encoding="utf-8",
    )

def main():
    diff = get_git_diff()
    if not diff.strip():
        print("No changes in Chapters/*.tex detected.")
        return

    print("Fetching review from Groq...")
    structured_diff = parse_diff(diff)
    print("Structured diff for review:\n", structured_diff)
    review = get_groq_review(structured_diff)
    print("Review received:\n", review)

    write_feedback(review)
    print("feedback.md written — workflow will post the PR comment.")

if __name__ == "__main__":
    main()
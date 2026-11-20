---
name: explain
description: Explain concepts, mechanisms, procedures, or differences with ASD-STE100-inspired language and focused visuals. Use for STE-style explanations, simplified technical explanations, or requests to understand a topic through diagrams, trees, pseudocode, or diffs. Match the user's language and add visuals when useful. Not for code implementation, full website design, or formal standards certification.
---

# Explain

Help the user understand, assess, or act on the specified topic. Apply ASD-STE100-inspired principles to the prose and choose the smallest visual that makes the key relationships clear.

## Identify the topic

Use the request and conversation to identify the topic, audience, and purpose. Write for a reader who knows the basic context but is unfamiliar with the topic. Honor the user's requested depth and format.

Use the language explicitly requested by the user. Otherwise, match the language of their current request, not that of quoted material, source code, or these instructions. For mixed-language or language-neutral requests, use the main language of the surrounding conversation. Apply this choice to prose and visual labels while preserving exact identifiers and UI labels.

If the user invokes the skill without a topic and the context provides none, ask what they want explained. Otherwise, explain directly. Clarify only ambiguities that would change the answer; do not require a fixed intake form.

## Write the explanation

1. Answer the main question in one or two sentences. Then add the mechanism, conditions, or examples needed to understand it.
2. Express one main idea per sentence. Prefer active voice and identify who does what to which object. Keep connecting words that make the meaning complete.
3. Use one name for each concept. Explain necessary terms and abbreviations on first use. Preserve the exact spelling of code identifiers, UI labels, and product names.
4. Make references explicit. When several objects are present, repeat the name instead of using an ambiguous pronoun.
5. Put a condition before the action it controls. Use clear if-then statements. Distinguish requirements, recommendations, and permissions, and distinguish all conditions from any condition.
6. Replace abstract phrases with concrete actions. For example, replace “perform a configuration adjustment” with “change the configuration.” Preserve meaningful negations, limits, values, units, and exceptions.
7. Match the structure to the question: definitions and examples for concepts, causes and results for mechanisms, shared dimensions for comparisons, and numbered steps for procedures. Use only structure that helps understanding.
8. Start procedural steps with action verbs and give each step one main action. Place necessary prerequisites or hazard notices before the relevant step. Explain how to confirm key results. Explaining an operation does not authorize its execution.

A short question can need only one paragraph. Expand complex answers as needed; do not remove essential information to meet a fixed sentence or word count. Use analogies as aids and identify where they stop applying.

## Choose the smallest view

Decide whether the reader needs a definition or condition, or needs to see order, relationships, hierarchy, or change. Use prose alone when it is sufficient. When a visual reduces the effort of understanding, start with one suitable view. Honor explicit requests for visuals or text only.

| What needs explanation | Preferred view |
| --- | --- |
| Branches, algorithms, or decision logic | Pseudocode in a `text` block |
| Call order and hierarchy | Call tree; sequence diagram for asynchronous interactions |
| UI structure and state ownership | Component tree with relevant state, module boundaries, and verified paths |
| File responsibilities or directory changes | Shallow file tree with short responsibility notes |
| Component interactions, data flow, or state transitions | Mermaid sequence, flow, or state diagram |
| Local changes in a known structure | A `diff` matching the code, tree, or pseudocode being explained |
| Options compared on shared dimensions | Short comparison table |
| UI layouts, visual state comparisons, or concepts too dense for ordinary diagrams | One focused standalone HTML file |

Place each visual next to the text it supports. Use consistent terms and explicit conditions in visual labels. Keep only the nodes, calls, files, states, and boundaries needed for the current question. Use prose for constraints that the visual cannot express well; do not repeat every label in prose.

When explaining real code, inspect the relevant implementation before drawing it. Distinguish actual structures, proposed structures, and conceptual sketches. Do not present unverified calls or paths as facts. Label pseudocode and structural sketches so readers do not mistake them for executable code.

Show a complete block when most of it is new, omitted context would hide ownership or order, or the user needs a complete copyable target. Verify both the old and new structures when explaining a change.

For HTML, use real labels and data from the topic. Match the product's colors, type, spacing, and components when that context is available; otherwise use a simple, readable style. Support desktop and mobile sizes. Save as `explain-{topic}.html` in a user-specified location or a scratch/temp directory so it does not pollute a clean Git working tree (if saved inside a repo, note that it is a scratch file), open it with the host's preview tool when available, and provide a file link. Check the content, file accessibility, and available rendered output. State when rendering was not checked. Add interaction only when it helps understanding; do not expand an explanation into full website development.

## Language and standards boundary

Chinese output adapts STE principles. Use natural, concise Chinese. Do not apply English word counts or the English dictionary as Chinese compliance criteria. Do not append a standards disclaimer to every ordinary explanation.

For English output, also use short sentences, stable terms, and clear actions. Describe specific compliance checks only after obtaining the applicable rules and dictionary and checking them individually. Short sentences or automated readability scores do not prove ASD-STE100 compliance.

For strict compliance, rule numbers, approved vocabulary, or a specific edition, read [Standard sources and verification limits](references/standard.md). Identify checks that lack supporting material. A draft can be provided for later verification, but do not claim certification or full compliance without evidence.

## Check before delivery

- Preserve the original causes, conditions, negations, order, values, and limits.
- Separate facts, inferences, and unknowns. Identify missing source information instead of turning a simplified explanation into an unsupported certainty.
- Check that terms are consistent, action targets are clear, and steps are executable.
- Check that visuals and prose agree on names, direction, conditions, and order. Visual omissions must not change the meaning.
- Deliver the explanation directly and remove unnecessary preamble. Show before-and-after edits to the explanation's own wording, or its checking process, only when requested. This restriction does not apply to diffs used to explain changes in the subject: choose those under “Choose the smallest view.”

## Examples

Use these two compact patterns as a baseline (write prose and labels in the selected response language). For full output-shape examples (pseudocode, call trees, component trees, file trees, Mermaid, subject-matched diffs, and HTML), read [Output shape examples](references/examples.md).

### Concept: short prose with a conceptual sketch

Request: “Explain visually why a cache can return old data.”

Explanation: “If the source data has changed but the cache has not updated, reading the cache can return old data.”

```text
Conceptual sketch:
Source data: B (updated)
Cached data: A (not yet updated)
Program → Read cache → Return A (old data)
```

“The cache policy determines when the cache updates.”

### Simple rule: prose only

Request: “Simplify this rule: Old files may be deleted only after backup verification succeeds.”

Explanation: “Verify the backup first. Delete the old files only if verification succeeds.”

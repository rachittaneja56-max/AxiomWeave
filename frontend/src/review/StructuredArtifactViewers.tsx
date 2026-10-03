import { MarkdownDocument } from "../components/MarkdownDocument";
import type {
  InfographicBlock,
  InfographicDocument,
  VideoPackageDocument,
} from "../types";

export function InfographicViewer({ value }: { value: InfographicDocument }) {
  return (
    <article className="structured-artifact structured-artifact--infographic">
      <header>
        <p className="eyebrow">Editable infographic specification</p>
        <h2>{value.title}</h2>
        {value.subtitle && (
          <p className="structured-artifact__subtitle">{value.subtitle}</p>
        )}
        {value.key_message && (
          <p className="structured-artifact__message">{value.key_message}</p>
        )}
      </header>
      <div className="structured-artifact__blocks">
        {value.blocks.map((block, index) => (
          <InfographicBlockView key={index} block={block} />
        ))}
      </div>
      <aside className="structured-artifact__direction">
        <strong>Visual direction</strong>
        <p>{value.visual_direction}</p>
      </aside>
    </article>
  );
}

function InfographicBlockView({ block }: { block: InfographicBlock }) {
  if (block.type === "section") {
    return (
      <section className="structured-artifact__card">
        <h3>{block.heading}</h3>
        <MarkdownDocument content={block.body} />
      </section>
    );
  }
  if (block.type === "callout") {
    return (
      <aside className="structured-artifact__callout">
        <span>{block.label}</span>
        <strong>{block.value}</strong>
        {block.explanation && <p>{block.explanation}</p>}
      </aside>
    );
  }
  return (
    <section className="structured-artifact__card">
      <h3>{block.heading}</h3>
      <dl className="structured-artifact__data">
        {block.rows.map((row, index) => (
          <div key={index}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
            {row.note && <small>{row.note}</small>}
          </div>
        ))}
      </dl>
    </section>
  );
}

export function InfographicEditor({
  value,
  onChange,
}: {
  value: InfographicDocument;
  onChange: (value: InfographicDocument) => void;
}) {
  function updateBlock(index: number, block: InfographicBlock) {
    onChange({
      ...value,
      blocks: value.blocks.map((item, itemIndex) =>
        itemIndex === index ? block : item,
      ),
    });
  }

  return (
    <div className="structured-editor">
      <p className="eyebrow">Editing infographic specification</p>
      <label htmlFor="infographic-title">Title</label>
      <input
        id="infographic-title"
        value={value.title}
        onChange={(event) => onChange({ ...value, title: event.target.value })}
      />
      <label htmlFor="infographic-subtitle">Subtitle</label>
      <input
        id="infographic-subtitle"
        value={value.subtitle}
        onChange={(event) =>
          onChange({ ...value, subtitle: event.target.value })
        }
      />
      <label htmlFor="infographic-message">Key message</label>
      <textarea
        id="infographic-message"
        rows={2}
        value={value.key_message}
        onChange={(event) =>
          onChange({ ...value, key_message: event.target.value })
        }
      />
      <label htmlFor="infographic-direction">Visual direction</label>
      <textarea
        id="infographic-direction"
        rows={2}
        value={value.visual_direction}
        onChange={(event) =>
          onChange({ ...value, visual_direction: event.target.value })
        }
      />
      <div className="structured-editor__blocks">
        {value.blocks.map((block, index) => (
          <fieldset className="structured-editor__block" key={index}>
            <legend>
              {block.type === "section"
                ? "Section"
                : block.type === "callout"
                  ? "Callout"
                  : "Data rows"}{" "}
              {index + 1}
            </legend>
            {block.type === "section" ? (
              <>
                <label htmlFor={`infographic-block-${index}-heading`}>
                  Heading
                </label>
                <input
                  id={`infographic-block-${index}-heading`}
                  value={block.heading}
                  onChange={(event) =>
                    updateBlock(index, {
                      ...block,
                      heading: event.target.value,
                    })
                  }
                />
                <label htmlFor={`infographic-block-${index}-body`}>Body</label>
                <textarea
                  id={`infographic-block-${index}-body`}
                  rows={3}
                  value={block.body}
                  onChange={(event) =>
                    updateBlock(index, { ...block, body: event.target.value })
                  }
                />
              </>
            ) : block.type === "callout" ? (
              <>
                <label htmlFor={`infographic-block-${index}-label`}>
                  Label
                </label>
                <input
                  id={`infographic-block-${index}-label`}
                  value={block.label}
                  onChange={(event) =>
                    updateBlock(index, { ...block, label: event.target.value })
                  }
                />
                <label htmlFor={`infographic-block-${index}-value`}>
                  Value
                </label>
                <input
                  id={`infographic-block-${index}-value`}
                  value={block.value}
                  onChange={(event) =>
                    updateBlock(index, { ...block, value: event.target.value })
                  }
                />
                <label htmlFor={`infographic-block-${index}-explanation`}>
                  Explanation
                </label>
                <textarea
                  id={`infographic-block-${index}-explanation`}
                  rows={2}
                  value={block.explanation}
                  onChange={(event) =>
                    updateBlock(index, {
                      ...block,
                      explanation: event.target.value,
                    })
                  }
                />
              </>
            ) : (
              <>
                <label htmlFor={`infographic-block-${index}-heading`}>
                  Heading
                </label>
                <input
                  id={`infographic-block-${index}-heading`}
                  value={block.heading}
                  onChange={(event) =>
                    updateBlock(index, {
                      ...block,
                      heading: event.target.value,
                    })
                  }
                />
                {block.rows.map((row, rowIndex) => (
                  <div className="structured-editor__row" key={rowIndex}>
                    <label
                      htmlFor={`infographic-block-${index}-row-${rowIndex}-label`}
                    >
                      Label
                    </label>
                    <input
                      id={`infographic-block-${index}-row-${rowIndex}-label`}
                      value={row.label}
                      onChange={(event) =>
                        updateBlock(index, {
                          ...block,
                          rows: block.rows.map((item, itemIndex) =>
                            itemIndex === rowIndex
                              ? { ...item, label: event.target.value }
                              : item,
                          ),
                        })
                      }
                    />
                    <label
                      htmlFor={`infographic-block-${index}-row-${rowIndex}-value`}
                    >
                      Value
                    </label>
                    <input
                      id={`infographic-block-${index}-row-${rowIndex}-value`}
                      value={row.value}
                      onChange={(event) =>
                        updateBlock(index, {
                          ...block,
                          rows: block.rows.map((item, itemIndex) =>
                            itemIndex === rowIndex
                              ? { ...item, value: event.target.value }
                              : item,
                          ),
                        })
                      }
                    />
                    <label
                      htmlFor={`infographic-block-${index}-row-${rowIndex}-note`}
                    >
                      Note
                    </label>
                    <input
                      id={`infographic-block-${index}-row-${rowIndex}-note`}
                      value={row.note}
                      onChange={(event) =>
                        updateBlock(index, {
                          ...block,
                          rows: block.rows.map((item, itemIndex) =>
                            itemIndex === rowIndex
                              ? { ...item, note: event.target.value }
                              : item,
                          ),
                        })
                      }
                    />
                    <button
                      type="button"
                      className="button-secondary"
                      disabled={block.rows.length === 1}
                      onClick={() =>
                        updateBlock(index, {
                          ...block,
                          rows: block.rows.filter(
                            (_, itemIndex) => itemIndex !== rowIndex,
                          ),
                        })
                      }
                    >
                      Remove data row
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  className="button-secondary"
                  disabled={block.rows.length >= 8}
                  onClick={() =>
                    updateBlock(index, {
                      ...block,
                      rows: [...block.rows, { label: "", value: "", note: "" }],
                    })
                  }
                >
                  Add data row
                </button>
              </>
            )}
            <button
              type="button"
              className="button-secondary"
              disabled={value.blocks.length === 1}
              onClick={() =>
                onChange({
                  ...value,
                  blocks: value.blocks.filter(
                    (_, itemIndex) => itemIndex !== index,
                  ),
                })
              }
            >
              Remove block
            </button>
          </fieldset>
        ))}
      </div>
      <button
        type="button"
        className="button-secondary"
        disabled={value.blocks.length >= 12}
        onClick={() =>
          onChange({
            ...value,
            blocks: [
              ...value.blocks,
              { type: "section", heading: "", body: "" },
            ],
          })
        }
      >
        Add section
      </button>
    </div>
  );
}

export function VideoPackageViewer({ value }: { value: VideoPackageDocument }) {
  return (
    <article className="structured-artifact structured-artifact--video">
      <header>
        <p className="eyebrow">Editable video production package</p>
        <h2>{value.title}</h2>
        <p className="structured-artifact__message">{value.concept}</p>
      </header>
      <div className="structured-artifact__scenes">
        {value.scenes.map((scene, index) => (
          <section className="structured-artifact__card" key={index}>
            <p className="eyebrow">Scene {index + 1}</p>
            <h3>{scene.title}</h3>
            {scene.narration && (
              <div>
                <strong>Narration</strong>
                <p>{scene.narration}</p>
              </div>
            )}
            {scene.on_screen_text.length > 0 && (
              <div>
                <strong>On-screen text</strong>
                <ul>
                  {scene.on_screen_text.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <strong>Visual direction</strong>
              <p>{scene.visual_direction}</p>
            </div>
            {scene.transition_notes && (
              <p>
                <strong>Transition notes:</strong> {scene.transition_notes}
              </p>
            )}
          </section>
        ))}
      </div>
    </article>
  );
}

export function VideoPackageEditor({
  value,
  onChange,
}: {
  value: VideoPackageDocument;
  onChange: (value: VideoPackageDocument) => void;
}) {
  function updateScene(
    index: number,
    scene: VideoPackageDocument["scenes"][number],
  ) {
    onChange({
      ...value,
      scenes: value.scenes.map((item, itemIndex) =>
        itemIndex === index ? scene : item,
      ),
    });
  }

  return (
    <div className="structured-editor">
      <p className="eyebrow">Editing video production package</p>
      <label htmlFor="video-package-title">Title</label>
      <input
        id="video-package-title"
        value={value.title}
        onChange={(event) => onChange({ ...value, title: event.target.value })}
      />
      <label htmlFor="video-package-concept">Concept / hook</label>
      <textarea
        id="video-package-concept"
        rows={3}
        value={value.concept}
        onChange={(event) =>
          onChange({ ...value, concept: event.target.value })
        }
      />
      {value.scenes.map((scene, index) => (
        <fieldset className="structured-editor__block" key={index}>
          <legend>Scene {index + 1}</legend>
          <label htmlFor={`video-scene-${index}-title`}>Scene title</label>
          <input
            id={`video-scene-${index}-title`}
            value={scene.title}
            onChange={(event) =>
              updateScene(index, { ...scene, title: event.target.value })
            }
          />
          <label htmlFor={`video-scene-${index}-narration`}>Narration</label>
          <textarea
            id={`video-scene-${index}-narration`}
            rows={4}
            value={scene.narration}
            onChange={(event) =>
              updateScene(index, { ...scene, narration: event.target.value })
            }
          />
          <label htmlFor={`video-scene-${index}-screen`}>
            On-screen text (one line per item)
          </label>
          <textarea
            id={`video-scene-${index}-screen`}
            rows={3}
            value={scene.on_screen_text.join("\n")}
            onChange={(event) =>
              updateScene(index, {
                ...scene,
                on_screen_text: event.target.value.split("\n").filter(Boolean),
              })
            }
          />
          <label htmlFor={`video-scene-${index}-visual`}>
            Visual direction
          </label>
          <textarea
            id={`video-scene-${index}-visual`}
            rows={2}
            value={scene.visual_direction}
            onChange={(event) =>
              updateScene(index, {
                ...scene,
                visual_direction: event.target.value,
              })
            }
          />
          <label htmlFor={`video-scene-${index}-transition`}>
            Transition / delivery notes
          </label>
          <input
            id={`video-scene-${index}-transition`}
            value={scene.transition_notes}
            onChange={(event) =>
              updateScene(index, {
                ...scene,
                transition_notes: event.target.value,
              })
            }
          />
          <button
            type="button"
            className="button-secondary"
            disabled={value.scenes.length === 1}
            onClick={() =>
              onChange({
                ...value,
                scenes: value.scenes.filter(
                  (_, itemIndex) => itemIndex !== index,
                ),
              })
            }
          >
            Remove scene
          </button>
        </fieldset>
      ))}
      <button
        type="button"
        className="button-secondary"
        disabled={value.scenes.length >= 16}
        onClick={() =>
          onChange({
            ...value,
            scenes: [
              ...value.scenes,
              {
                title: "",
                narration: "",
                on_screen_text: [],
                visual_direction: "",
                transition_notes: "",
              },
            ],
          })
        }
      >
        Add scene
      </button>
    </div>
  );
}

import { useEffect, useState } from "react";
import type { SettingsField, SettingsForm } from "../api/types";
import { ukDateTime } from "../lib/format";

interface Props {
  form: SettingsForm;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}

type Draft = Record<string, string>;

function toText(field: SettingsField): string {
  if (field.type === "list") return Array.isArray(field.value) ? (field.value as unknown[]).join(", ") : "";
  if (field.type === "boolean") return field.value ? "true" : "false";
  if (field.value === null || field.value === undefined) return "";
  return String(field.value);
}

function fromText(field: SettingsField, text: string): unknown {
  if (field.type === "number") return Number(text);
  if (field.type === "integer") return Number(text);
  if (field.type === "boolean") return text === "true";
  if (field.type === "list") return text.split(",").map((s) => s.trim()).filter(Boolean);
  return text;
}

// The settings form, built from the field definitions GET /admin/settings returns. Only
// changed, writable fields are sent with PUT; secrets are masked and read only.
export default function SettingsFormView({ form, onSave }: Props) {
  const [draft, setDraft] = useState<Draft>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next: Draft = {};
    for (const group of form.groups) for (const field of group.fields) next[field.key] = toText(field);
    setDraft(next);
  }, [form]);

  const changed = (field: SettingsField) => draft[field.key] !== undefined && draft[field.key] !== toText(field);

  const submit = async () => {
    const values: Record<string, unknown> = {};
    for (const group of form.groups) for (const field of group.fields) if (field.writable && changed(field)) values[field.key] = fromText(field, draft[field.key]);
    if (Object.keys(values).length === 0) return;
    setSaving(true);
    try {
      await onSave(values);
    } finally {
      setSaving(false);
    }
  };

  const anyChanged = form.groups.some((g) => g.fields.some((f) => f.writable && changed(f)));

  return (
    <div>
      <p className="small muted">
        Source: {form.source}
        {form.updated_at ? ` · updated ${ukDateTime(form.updated_at)} by ${form.updated_by ?? "—"}` : ""}
        {form.storage?.path ? ` · ${form.storage.backend} ${form.storage.path}` : ""}
        {form.last_error ? ` · last error: ${form.last_error}` : ""}
      </p>
      {form.groups.map((group) => (
        <div key={group.id} style={{ marginBottom: "1rem" }}>
          <h3>{group.label}</h3>
          <table>
            <tbody>
              {group.fields.map((field) => (
                <tr key={field.key}>
                  <td style={{ width: "22%" }}>
                    <div>{field.label}</div>
                    <div className="small muted mono">{field.key}</div>
                  </td>
                  <td style={{ width: "33%" }}>
                    {field.type === "secret" ? (
                      <span className="mono">
                        {String(field.value)} <span className="small muted">({field.secret ?? "secret"}, {field.state ?? "—"})</span>
                      </span>
                    ) : field.type === "boolean" ? (
                      <select value={draft[field.key] ?? "false"} disabled={!field.writable} onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}>
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : field.type === "list" ? (
                      <textarea
                        rows={2}
                        style={{ width: "100%" }}
                        value={draft[field.key] ?? ""}
                        disabled={!field.writable}
                        onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}
                      />
                    ) : (
                      <input
                        className={field.type === "string" ? "" : "num"}
                        type={field.type === "string" ? "text" : "number"}
                        step={field.step ?? (field.type === "integer" ? 1 : "any")}
                        min={field.min ?? undefined}
                        max={field.max ?? undefined}
                        value={draft[field.key] ?? ""}
                        disabled={!field.writable}
                        onChange={(e) => setDraft({ ...draft, [field.key]: e.target.value })}
                      />
                    )}
                    {changed(field) && <span className="badge"> changed</span>}
                  </td>
                  <td className="small muted">{field.help ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <button className="primary" onClick={() => void submit()} disabled={!anyChanged || saving}>
        {saving ? "Saving…" : "Save changed settings"}
      </button>
    </div>
  );
}

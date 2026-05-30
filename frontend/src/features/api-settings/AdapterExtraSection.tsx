import type { AdapterExtraFieldSchema } from "../../entities/config/types";
import { AdapterExtraForm } from "./AdapterExtraForm";

interface AdapterExtraSectionProps {
  disabled: boolean;
  onChange: (key: string, value: unknown) => void;
  schema: Record<string, AdapterExtraFieldSchema>;
  title: string;
  values: Record<string, unknown>;
}

export function AdapterExtraSection({ disabled, onChange, schema, title, values }: AdapterExtraSectionProps) {
  return (
    <section className="section">
      <div className="section__header">
        <h2 className="section__title">{title}</h2>
      </div>
      <AdapterExtraForm disabled={disabled} onChange={onChange} schema={schema} values={values} />
    </section>
  );
}

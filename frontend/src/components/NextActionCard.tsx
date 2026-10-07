import type { NextAction } from "@/lib/api";

function actionTarget(action: NextAction): string {
  if (action.import_run_id) return "#canada-import";
  if (action.fact_id) return "#needs-attention";
  if (action.requirement_id) return "#documents";
  if (action.task_id) return "#needs-attention";
  if (action.document_id) return "#documents";
  if (action.target_state) return "#primary-action";
  if (action.preparation_path) return "#preparation-readiness";
  return "#overview";
}

export function NextActionCard({ action }: { action: NextAction }) {
  return (
    <section className="next-action" aria-labelledby="next-action-title">
      <p className="eyebrow">Backend recommendation</p>
      <h2 id="next-action-title">Next action</h2>
      <p>{action.title}</p>
      <a className="button button-secondary" href={actionTarget(action)}>
        Open relevant section
      </a>
    </section>
  );
}

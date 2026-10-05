import { WORKFLOW_STATES, type WorkflowState } from "@/lib/api";

export function WorkflowStepper({ current }: { current: WorkflowState }) {
  const currentIndex = WORKFLOW_STATES.indexOf(current);
  return (
    <div className="workflow-stepper" aria-label={`Workflow state: ${current}`}>
      {WORKFLOW_STATES.map((state, index) => (
        <div
          className={`workflow-step ${index < currentIndex ? "complete" : ""} ${state === current ? "current" : ""}`}
          aria-current={state === current ? "step" : undefined}
          key={state}
        >
          {state}
        </div>
      ))}
    </div>
  );
}

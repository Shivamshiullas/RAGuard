import type { DocumentVersion } from "../../types/documents";
import { processingSteps, STAGE_LABELS } from "../../utils/documents";

type StepState = "done" | "current" | "failed" | "pending";

interface ProcessingStagesProps {
  version: DocumentVersion;
}

export default function ProcessingStages({ version }: ProcessingStagesProps) {
  const steps = processingSteps(version.ocrRequired);
  const activeStage = version.stage === "failed" ? version.failedAt : version.stage;
  const activeIndex = activeStage ? steps.indexOf(activeStage) : -1;

  function stateOf(index: number): StepState {
    if (version.stage === "indexed" || index < activeIndex) return "done";
    if (index === activeIndex) return version.stage === "failed" ? "failed" : "current";
    return "pending";
  }

  return (
    <ol className="stages" aria-label="Processing stages">
      {steps.map((step, i) => {
        const state = stateOf(i);
        return (
          <li key={step} className={`stages__step stages__step--${state}`}>
            <span className="stages__dot" aria-hidden="true" />
            {STAGE_LABELS[step]}
            <span className="visually-hidden"> ({state})</span>
          </li>
        );
      })}
    </ol>
  );
}

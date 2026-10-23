interface ExampleQuestionsProps {
  questions: string[];
  onSelect: (question: string) => void;
  disabled?: boolean;
}

export default function ExampleQuestions({ questions, onSelect, disabled }: ExampleQuestionsProps) {
  return (
    <ul className="example-questions" aria-label="Example questions">
      {questions.map((q) => (
        <li key={q}>
          <button type="button" className="chip" onClick={() => onSelect(q)} disabled={disabled}>
            {q}
          </button>
        </li>
      ))}
    </ul>
  );
}

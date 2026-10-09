import { describeError } from "../api/client";

export default function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { code, message } = describeError(error);
  return (
    <div className="error" role="alert">
      <div>
        <code>{code}</code> {message}
      </div>
      {onRetry && (
        <button className="small" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

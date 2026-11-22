import React, { createContext, useContext, useState } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { X } from "lucide-react";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const Button: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "secondary" | "outline" | "ghost" | "danger" | "success";
    size?: "sm" | "md" | "lg";
  }
> = ({ className, variant = "primary", size = "md", ...props }) => {
  const variants = {
    primary: "bg-[#76010d] text-white hover:bg-[#5d010a] shadow-sm",
    secondary: "bg-slate-900 text-white hover:bg-slate-800 shadow-sm",
    outline: "border border-slate-300 bg-white text-slate-800 hover:bg-[#fdf8f0]",
    ghost: "bg-transparent text-slate-700 hover:bg-[#fdf8f0]",
    danger: "bg-red-600 text-white hover:bg-red-700 shadow-sm",
    success: "bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm",
  };
  const sizes = {
    sm: "px-3 py-1.5 text-xs rounded-lg",
    md: "px-4 py-2 text-sm rounded-xl",
    lg: "px-5 py-3 text-base rounded-xl",
  };
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]",
        variants[variant],
        sizes[size],
        className
      )}
      {...props}
    />
  );
};

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div className={cn("rounded-2xl border border-slate-200/80 bg-white shadow-sm", className)} {...props} />
);

export const Badge: React.FC<
  React.HTMLAttributes<HTMLSpanElement> & {
    tone?: "default" | "green" | "amber" | "red" | "blue" | "slate";
  }
> = ({ className, tone = "default", ...props }) => {
  const tones = {
    default: "bg-[#fdf8f0] text-[#76010d] border-[#76010d]/25",
    green: "bg-emerald-50 text-emerald-700 border-emerald-200",
    amber: "bg-amber-50 text-amber-800 border-amber-200",
    red: "bg-red-50 text-red-700 border-red-200",
    blue: "bg-sky-50 text-sky-700 border-sky-200",
    slate: "bg-slate-100 text-slate-700 border-slate-200",
  };
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold", tones[tone], className)}
      {...props}
    />
  );
};

export const Input: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({ className, ...props }) => (
  <input
    className={cn(
      "w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-[#76010d] focus:outline-none focus:ring-2 focus:ring-[#76010d]/20",
      className
    )}
    {...props}
  />
);

export const Select: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({ className, ...props }) => (
  <select
    className={cn(
      "w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm text-slate-900 focus:border-[#76010d] focus:outline-none focus:ring-2 focus:ring-[#76010d]/20",
      className
    )}
    {...props}
  />
);

export const Modal: React.FC<{
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  maxWidth?: string;
}> = ({ open, onClose, title, children, maxWidth = "max-w-lg" }) => {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm">
      <div className={cn("w-full rounded-2xl bg-white shadow-2xl border border-slate-200 max-h-[90vh] flex flex-col", maxWidth)}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
};

interface ToastItem {
  id: number;
  message: string;
  tone: "success" | "error" | "info";
}

const ToastContext = createContext<{ pushToast: (msg: string, tone?: "success" | "error" | "info") => void }>({
  pushToast: () => {},
});

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const pushToast = (message: string, tone: "success" | "error" | "info" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, tone }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  };
  return (
    <ToastContext.Provider value={{ pushToast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 no-print">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "rounded-xl px-4 py-3 text-sm font-semibold text-white shadow-lg",
              t.tone === "success" && "bg-emerald-600",
              t.tone === "error" && "bg-red-600",
              t.tone === "info" && "bg-slate-900"
            )}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => useContext(ToastContext);

export function crowdBadgeTone(level?: string): "green" | "amber" | "red" | "slate" {
  if (level === "LOW") return "green";
  if (level === "MODERATE") return "amber";
  if (level === "HIGH" || level === "VERY_HIGH") return "red";
  return "slate";
}

export const ConfirmModal: React.FC<{
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  confirmVariant?: "danger" | "primary" | "success";
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
  busy?: boolean;
}> = ({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  confirmVariant = "danger",
  onConfirm,
  onCancel,
  busy = false,
}) => (
  <Modal open={open} onClose={onCancel} title={title} maxWidth="max-w-md">
    <div className="space-y-4">
      <p className="text-sm text-slate-700 leading-relaxed">{message}</p>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button size="sm" variant={confirmVariant} onClick={onConfirm} disabled={busy}>
          {busy ? "Working..." : confirmLabel}
        </Button>
      </div>
    </div>
  </Modal>
);

export const InputPromptModal: React.FC<{
  open: boolean;
  title: string;
  label: string;
  placeholder?: string;
  defaultValue?: string;
  submitLabel?: string;
  onSubmit: (value: string) => void | Promise<void>;
  onCancel: () => void;
  busy?: boolean;
}> = ({
  open,
  title,
  label,
  placeholder,
  defaultValue = "",
  submitLabel = "Submit",
  onSubmit,
  onCancel,
  busy = false,
}) => {
  const [val, setVal] = useState(defaultValue);
  React.useEffect(() => {
    if (open) setVal(defaultValue);
  }, [open, defaultValue]);

  return (
    <Modal open={open} onClose={onCancel} title={title} maxWidth="max-w-md">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!val.trim()) return;
          void onSubmit(val.trim());
        }}
        className="space-y-4"
      >
        <div>
          <label className="mb-1 block text-xs font-bold text-slate-700">{label}</label>
          <Input autoFocus required value={val} onChange={(e) => setVal(e.target.value)} placeholder={placeholder} />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" size="sm" variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" size="sm" variant="primary" disabled={busy || !val.trim()}>
            {busy ? "Saving..." : submitLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
};

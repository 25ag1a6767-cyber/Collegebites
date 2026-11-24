import React from "react";
import { BrandLogo } from "../branding/BrandLogo";
import { Button, Card } from "../ui/Primitives";

interface State {
  hasError: boolean;
  errorMessage: string;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      errorMessage: error?.message || "An unexpected interface error occurred.",
    };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Log sanitized client diagnostic to console without exposing tokens
    console.error("CollegeBites UI ErrorBoundary caught error:", error?.message, info?.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-[#fdf8f0] p-4">
          <Card className="max-w-md w-full p-6 text-center space-y-4">
            <BrandLogo size="md" className="mx-auto" />
            <h1 className="text-lg font-extrabold text-slate-900">Something went wrong</h1>
            <p className="text-xs text-slate-600">{this.state.errorMessage}</p>
            <div className="flex justify-center gap-2">
              <Button
                size="sm"
                variant="primary"
                onClick={() => {
                  this.setState({ hasError: false, errorMessage: "" });
                  window.location.reload();
                }}
              >
                Reload Page
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  this.setState({ hasError: false, errorMessage: "" });
                  window.location.href = "/";
                }}
              >
                Return Home
              </Button>
            </div>
          </Card>
        </div>
      );
    }
    return this.props.children;
  }
}

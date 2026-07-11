import { Suspense } from "react";
import { AuthForm } from "../signin/AuthForm";

export default function SignUpPage() {
  return (
    <Suspense fallback={null}>
      <AuthForm mode="signup" />
    </Suspense>
  );
}

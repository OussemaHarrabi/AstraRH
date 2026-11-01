import { Suspense } from "react";
import { Shell } from "@/ui/Shell";
import { Loading } from "@/ui/kit";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<Loading />}>
      <Shell>{children}</Shell>
    </Suspense>
  );
}

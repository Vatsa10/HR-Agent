import { Sidebar } from "@/components/Sidebar";

export default function DashLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-paper">
      <Sidebar />
      <main className="md:ml-60">
        <div className="mx-auto w-full max-w-[1080px] px-5 py-8 md:px-10 md:py-12">
          {children}
        </div>
      </main>
    </div>
  );
}

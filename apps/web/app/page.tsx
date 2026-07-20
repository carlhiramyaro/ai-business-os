import Link from "next/link";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

const STEPS = [
  {
    title: "Upload your data",
    description: "Sales, inventory, and expense CSVs — however messy your column headers are.",
  },
  {
    title: "Get a Business Health Report",
    description: "A finance, inventory, marketing, and operations analysis, synthesized into one clear report.",
  },
  {
    title: "Chat with your data",
    description: "Ask follow-up questions and get answers grounded in your own report and numbers.",
  },
];

export default function Home() {
  return (
    <div className="flex flex-1 flex-col items-center">
      <section className="flex w-full max-w-3xl flex-col items-center gap-6 px-6 py-24 text-center">
        <span className="rounded-full bg-brand/10 px-3 py-1 text-xs font-medium text-brand">
          AI Business Analyst for small businesses
        </span>
        <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
          Turn your spreadsheets into a business health report.
        </h1>
        <p className="max-w-xl text-lg text-muted">
          Ledger reads your sales, inventory, and expense data, runs it through a team of AI analysts, and gives
          you a clear picture of where your business stands — plus a chat interface to ask anything else.
        </p>
        <div className="flex gap-3">
          <Link href="/login">
            <Button className="px-6 py-3 text-base">Get started</Button>
          </Link>
        </div>
      </section>

      <section className="grid w-full max-w-4xl grid-cols-1 gap-4 px-6 pb-24 sm:grid-cols-3">
        {STEPS.map((step, index) => (
          <Card key={step.title} className="flex flex-col gap-2">
            <span className="text-sm font-medium text-brand">Step {index + 1}</span>
            <h2 className="font-medium text-foreground">{step.title}</h2>
            <p className="text-sm text-muted">{step.description}</p>
          </Card>
        ))}
      </section>
    </div>
  );
}

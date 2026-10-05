import Link from "next/link";
import { CaseListClient } from "@/components/CaseListClient";

export default function CasesPage() {
  return <><div className="page-heading"><div><p className="eyebrow">Employee workspace</p><h1>Cases</h1><p className="subtitle">Open a case to manage its data and workflow.</p></div><Link className="button" href="/cases/new">New case</Link></div><CaseListClient /></>;
}

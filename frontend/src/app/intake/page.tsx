import { IntakeQueueClient } from "@/components/IntakeQueueClient";


export default function IntakePage() {
  return <><div className="page-heading"><div><p className="eyebrow">Automated intake</p><h1>Incoming submissions</h1><p className="subtitle">Successful submissions process automatically. Only failures and genuine exceptions require attention.</p></div></div><IntakeQueueClient /></>;
}

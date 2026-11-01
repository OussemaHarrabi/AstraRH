// The narration, one entry per shot. record.mjs plays the matching actions for each.
export const NARRATION = {
  hero: "This is AstraRH. HR teams drown in CVs, emails and scheduling, and most AI tools answer by acting on their own. We took the opposite view. The agents do the work. You make the calls.",
  work: "Six jobs come off your desk: ranking CVs, sorting the inbox, drafting replies, following up, finding interview times, and answering policy questions. Let's see a real day, on real data, with real model calls.",
  overview: "Nadia is a recruiter. Her morning starts here. This is her crew of agents, and each face shows what that agent is really doing. Everything they prepared is waiting for her decision. Nothing has been sent.",
  ranking: "Forty-two people applied for Backend Engineer. Idris read every CV with the name, contact details and photo hidden. Then Nour ranked them. And the score isn't a model's opinion. It's a formula.",
  why: "Here is why Sofien ranks first. Every point traces back to a sentence in the CV, checked word for word. Press recalculate, and the same inputs give exactly the same score.",
  attack: "Some CVs are written for the machine. This one hides instructions in white text, asking to be ranked first. We delete them from the file before any model reads it. In our tests, the attack scores exactly like its clean twin.",
  criteria: "A person stays in charge of what counts. When a job is created, Mira drafts the criteria, and a recruiter adjusts and approves them. Nothing is ranked until that happens.",
  inbox: "Now the inbox. Salem sorted this morning's email by type and urgency. Legal threats, salary talks and visa questions always go to a person, whatever the model thinks.",
  reply: "Yara drafted this reply using only this candidate's file, so one person's data can't leak into another's email. Nadia can edit it. Change one word, and any earlier approval is void, because approval binds to a hash of the exact content.",
  send: "She approves. Only now does a separate process, on its own network, send it. There it is, in the mailbox. The agent itself has no way to send anything.",
  booking: "Dali holds three real free times, so nobody else gets them. Nizar replied by email: Tuesday works for me. Dali read it, quoted it, and proposed the booking. Nadia approves, the calendar is checked again, and the interview is booked.",
  ask: "Employees get answers too. Hela answers only from policies they're allowed to read, and shows the exact sentence. Ask about something restricted, and she doesn't guess. She passes it to HR.",
  agents: "Every agent's work is open to inspection: each run, step, model, token and cost. A full screening run costs about two cents.",
  graph: "And here is how it all connects. Each line means a sentence in that CV proves that criterion. Switch view, and you see the real path of work: an event wakes an agent, the agent proposes, a person decides, the executor acts.",
  payroll: "It continues after the hire. New joiners get onboarding plans. Payroll is calculated by code, never by a model, and big decisions need two different people and a fresh password.",
  audit: "Finally, proof. Every action is written to a chain of hashes. Verify it, and each entry is recomputed. Edit one row, and the chain breaks.",
  close: "AstraRH. The agents do the work. You make the calls.",
};

export const ORDER = Object.keys(NARRATION);

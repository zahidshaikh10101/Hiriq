/* Hiriq — demo data for the admin console.
   When the Python backend is ready, admin.js will fetch these from /api/... instead.
   Keep the same shapes and the swap is painless. */
(function () {
  function series(n, base, amp, seed) {
    var s = seed;
    function r() { s = (s * 9301 + 49297) % 233280; return s / 233280; }
    var out = [];
    for (var i = 0; i < n; i++) out.push(Math.round(base + amp * (0.55 * Math.sin(i / 2.3) + r()) + i * (base / 60)));
    return out;
  }
  function labels(prefix, n) {
    var out = [];
    for (var i = 1; i <= n; i++) out.push(prefix + " " + i);
    return out;
  }

  window.HIRIQ_DEMO = {
    plans: [
      { id: "free", name: "Free", live: true },
      { id: "basic", name: "Basic", live: false },
      { id: "pro", name: "Pro", live: false },
      { id: "premium", name: "Premium", live: false }
    ],

    users: [
      { id: 1, name: "admin", email: "admin (this account)", phone: "—", designation: "Platform admin", company: "Hiriq", role: "admin", tier: "free", status: "Active", joined: "1 Oct 2026", last: "now", locked: true },
      { id: 2, name: "Aarav Mehta", email: "aarav.mehta@example.com", phone: "+91 98200 11234", designation: "Data Analyst", company: "Northwind Analytics", role: "candidate", tier: "free", status: "Active", joined: "12 Oct 2026", last: "32 min ago" },
      { id: 3, name: "Priya Nair", email: "priya.nair@example.com", phone: "+91 99300 45678", designation: "Senior Talent Partner", company: "Bluefin Labs", role: "recruiter", tier: "free", status: "Active", joined: "8 Oct 2026", last: "4 min ago" },
      { id: 4, name: "Rohan Kulkarni", email: "rohan.k@example.com", phone: "+91 97690 22310", designation: "BI Developer", company: "Saffron Retail", role: "candidate", tier: "free", status: "Active", joined: "20 Oct 2026", last: "2 h ago" },
      { id: 5, name: "Sana Qureshi", email: "sana.q@example.com", phone: "+91 98670 55102", designation: "ML Engineer", company: "Orbitline", role: "candidate", tier: "free", status: "Suspended", joined: "3 Oct 2026", last: "9 days ago" },
      { id: 6, name: "Vikram Iyer", email: "vikram.iyer@example.com", phone: "+91 90040 78821", designation: "Hiring Manager", company: "Kestrel AI", role: "recruiter", tier: "free", status: "Active", joined: "14 Oct 2026", last: "yesterday" },
      { id: 7, name: "Neha Joshi", email: "neha.joshi@example.com", phone: "+91 98190 33467", designation: "Operations Lead", company: "Hiriq", role: "admin", tier: "free", status: "Active", joined: "2 Oct 2026", last: "1 h ago" },
      { id: 8, name: "Ananya Rao", email: "ananya.rao@example.com", phone: "+91 99870 61209", designation: "Recruitment Consultant", company: "Harbor Fintech", role: "recruiter", tier: "free", status: "Invited", joined: "28 Oct 2026", last: "never" }
    ],

    uploads: {
      "7d": { values: series(7, 260, 120, 3), labels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], sub: "Per day, last 7 days" },
      "30d": { values: series(30, 250, 140, 5), labels: labels("Day", 30), sub: "Per day, last 30 days" },
      "90d": { values: series(13, 1700, 700, 9), labels: labels("Week", 13), sub: "Per week, last 90 days" }
    },

    kpis: {
      "7d": [["Total users", "1,248", "+3.1%", true], ["Resumes scored", "2,140", "+8.4%", true], ["Jobs ingested", "6,410", "+5.0%", true], ["Alert open rate", "41%", "−1.2 pts", false]],
      "30d": [["Total users", "1,248", "+12.4%", true], ["Resumes scored", "8,920", "+15.2%", true], ["Jobs ingested", "27,300", "+9.8%", true], ["Alert open rate", "43%", "+2.0 pts", true]],
      "90d": [["Total users", "1,248", "+38%", true], ["Resumes scored", "24,600", "+41%", true], ["Jobs ingested", "48,210", "+27%", true], ["Alert open rate", "40%", "+0.5 pts", true]]
    },

    roleCounts: [["Candidates", 1104], ["Recruiters", 138], ["Admins", 6]],
    health: [["Job ingest", "good", "Running"], ["Alert email", "good", "Running"], ["LLM API", "warn", "Near rate limit"], ["Database", "good", "Healthy"]],
    funnel: [["Signed up", 1104], ["Uploaded a resume", 912], ["Scored against a job", 761], ["Applied from Hiriq", 344]],
    skillDemand: [["Python", 64], ["SQL", 58], ["Power BI", 31], ["Excel", 29], ["Pandas", 24], ["Spark", 21], ["AWS", 19], ["Tableau", 17]],
    activity: [
      ["Priya Nair ranked 42 resumes for Senior Data Analyst", "4 min ago", "a3"],
      ["Job ingest added 1,186 new postings", "2:10 am", "a1"],
      ["Aarav Mehta scored his resume against 6 jobs", "32 min ago", "a2"],
      ["Morning alerts sent to 806 candidates", "7:30 am", "a4"],
      ["admin changed Vikram Iyer to Recruiter", "Yesterday", "warn"]
    ],

    sources: [
      { id: "adzuna", name: "Adzuna", kind: "Job board API, key required" },
      { id: "remotive", name: "Remotive", kind: "Remote jobs API, public" },
      { id: "arbeitnow", name: "Arbeitnow", kind: "Job board API, public" },
      { id: "muse", name: "The Muse", kind: "Job board API, key required" },
      { id: "csv", name: "CSV upload", kind: "Manual file upload" }
    ],
    jobsAdded: series(14, 900, 260, 13), // 17–30 Oct
    activeCandidates: 1104,
    storedJobs: [
      ["Data Analyst", "Northwind Analytics", "Mumbai", "Adzuna", "2 h ago", "SQL, Power BI, Excel", 214],
      ["Data Scientist", "Bluefin Labs", "Pune", "Remotive", "5 h ago", "Python, scikit-learn, SQL", 188],
      ["GenAI Engineer", "Kestrel AI", "Bengaluru", "Arbeitnow", "Today", "Python, RAG, FastAPI", 96],
      ["BI Analyst", "Saffron Retail", "Remote", "The Muse", "Yesterday", "Tableau, SQL", 302],
      ["ML Engineer", "Orbitline", "Hyderabad", "Adzuna", "Yesterday", "Python, PyTorch, Docker", 77],
      ["Business Analyst", "Harbor Fintech", "Mumbai", "Remotive", "2 days ago", "Excel, SQL, Jira", 265],
      ["Analytics Engineer", "Lumen Data", "Bengaluru", "Adzuna", "2 days ago", "dbt, SQL, Airflow", 141],
      ["Product Analyst", "Mango Commerce", "Pune", "Arbeitnow", "3 days ago", "SQL, Python, A/B testing", 120]
    ],

    // Placeholders until the labeled evaluation set exists (see /ml/README.md)
    approaches: [["v0 hand-weighted formula", 0.61], ["TF-IDF keywords", 0.66], ["Embeddings", 0.74], ["Embeddings + LLM rerank", 0.79], ["Trained ranker (LightGBM)", 0.81]],
    ndcgWeekly: [0.62, 0.64, 0.66, 0.71, 0.73, 0.74, 0.78, 0.81],
    scoreBands: [12, 28, 55, 96, 148, 190, 212, 170, 98, 41],
    checks: [
      ["Sensitive fields in features", "Name, gender, photo, college excluded", "good", "Pass"],
      ["Score drift", "Mean score up 4 points this week", "warn", "Watch"],
      ["Explanations attached", "Every score has matched and missing skills", "good", "Pass"],
      ["Recruiter feedback labels", "38 new labels since last retrain", "good", "Ready"]
    ],

    audit: [
      ["30 Oct, 03:24", "Auth", "admin", "signed in"],
      ["30 Oct, 02:10", "Data", "system", "stored 1,186 new job postings after removing duplicates"],
      ["29 Oct, 22:41", "Users", "admin", "changed Vikram Iyer from Candidate to Recruiter"],
      ["29 Oct, 21:05", "Model", "Neha Joshi", "promoted ranker v0.4 to live"],
      ["29 Oct, 19:30", "Users", "Neha Joshi", "invited Ananya Rao as Recruiter"],
      ["29 Oct, 18:02", "Auth", "Sana Qureshi", "was blocked after 5 failed sign-ins"],
      ["29 Oct, 15:47", "Data", "Rohan Kulkarni", "requested a data export"],
      ["28 Oct, 11:12", "Users", "admin", "suspended Sana Qureshi"]
    ]
  };
})();

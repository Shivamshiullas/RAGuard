"""Generate synthetic academic PDFs for demos and tests.

All content describes a fictional institution ("Northfield Institute of Technology").
It is not a real policy document.

Usage:  python scripts/make_sample_docs.py [output_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

NAVY = (0.09, 0.17, 0.33)
TEAL = (0.05, 0.55, 0.55)
INSTITUTE = "Northfield Institute of Technology (fictional sample institution)"


def _page(doc: fitz.Document, title: str) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 40), INSTITUTE, fontsize=8, color=(0.4, 0.4, 0.4))
    page.insert_text((50, 70), title, fontsize=15, fontname="hebo", color=NAVY)
    page.draw_line((50, 80), (545, 80), color=TEAL, width=1)
    return page, 100


def _para(page: fitz.Page, y: float, text: str, size: float = 10.5, bold: bool = False) -> float:
    rect = fitz.Rect(50, y, 545, 800)
    remaining = page.insert_textbox(rect, text, fontsize=size, fontname="hebo" if bold else "helv")
    if remaining < 0:
        raise ValueError(f"text overflowed the page: {text[:40]}")
    return y + (rect.height - remaining) + 6


def _table(page: fitz.Page, y: float, rows: list[list[str]], widths: list[float]) -> float:
    x0 = 50
    for r, row in enumerate(rows):
        x = x0
        for c, cell in enumerate(row):
            rect = fitz.Rect(x, y, x + widths[c], y + 20)
            page.draw_rect(rect, color=(0.6, 0.6, 0.6), width=0.6,
                           fill=(0.88, 0.93, 0.97) if r == 0 else None)
            page.insert_textbox(rect + (4, 4, -2, 0), cell, fontsize=9, fontname="hebo" if r == 0 else "helv")
            x += widths[c]
        y += 20
    return y + 14


def regulations(out: Path) -> None:
    doc = fitz.open()
    p, y = _page(doc, "Academic Regulations for B.Tech Programmes 2026")
    y = _para(p, y, "1. Scope", bold=True)
    y = _para(p, y, "These regulations apply to all students admitted to the four-year B.Tech programme "
                    "from the academic year 2026-27 onwards. Where a department notice conflicts with these "
                    "regulations, the student should contact the Office of the Controller of Examinations.")
    y = _para(p, y, "2. Attendance Requirements", bold=True)
    y = _para(p, y, "A student must secure a minimum of 75% attendance in each course to be eligible to write "
                    "the end-semester examination of that course. Attendance is calculated from the first "
                    "instructional day to the last instructional day of the semester.")
    y = _para(p, y, "Condonation: a student with attendance between 65% and 75% may apply for condonation "
                    "on medical grounds by submitting a medical certificate from a registered medical "
                    "practitioner to the Head of Department within 7 days of returning to classes. "
                    "A condonation fee of Rs. 500 per course is payable. Condonation can be granted at most "
                    "twice during the programme.")
    y = _para(p, y, "A student with attendance below 65% in a course is not eligible for condonation and "
                    "must re-register for the course in a subsequent semester.")

    p, y = _page(doc, "3. Examination Eligibility and Assessment")
    y = _para(p, y, "3.1 Eligibility for end-semester examinations", bold=True)
    y = _para(p, y, "To be eligible for the end-semester examination a student must (a) satisfy the attendance "
                    "requirement in Section 2, (b) have no pending library dues, and (c) have registered "
                    "for the examination through the student portal before the published deadline.")
    y = _para(p, y, "3.2 Internal assessment procedure", bold=True)
    y = _para(p, y, "Each theory course is assessed out of 100 marks: 40 marks of continuous internal "
                    "evaluation (CIE) and 60 marks in the end-semester examination (ESE). The distribution "
                    "of internal marks is shown in Table 1.")
    y = _table(p, y, [["Component", "Marks", "Conducted in"],
                      ["Internal test 1", "15", "Week 6"],
                      ["Internal test 2", "15", "Week 12"],
                      ["Assignments / quizzes", "10", "Throughout semester"],
                      ["End-semester examination", "60", "After week 16"]], [200, 100, 195])
    y = _para(p, y, "Table 1: Distribution of marks for theory courses.", size=9)
    y = _para(p, y, "A student must obtain at least 40% in the ESE and at least 50% in the aggregate of CIE "
                    "and ESE to pass a course.")

    p, y = _page(doc, "4. Project Work and Submission")
    y = _para(p, y, "Final-year project reports must be submitted to the department in two hard copies and "
                    "one soft copy (PDF). The project submission deadline is two weeks before the start of "
                    "the end-semester examinations. Late submissions attract a penalty of 10% of the "
                    "project marks per week of delay.")
    y = _para(p, y, "5. Grade Distribution (previous year)", bold=True)
    y = _para(p, y, "Figure 1: Distribution of final grades across all B.Tech courses in 2025-26.")
    # Bar chart drawn with vector graphics so it is a real visual on the page.
    base_y, x = y + 190, 90
    grades = [("O", 9), ("A+", 18), ("A", 26), ("B+", 22), ("B", 14), ("C", 7), ("F", 4)]
    p.draw_line((80, base_y), (520, base_y), color=(0, 0, 0), width=0.8)
    p.draw_line((80, base_y), (80, base_y - 180), color=(0, 0, 0), width=0.8)
    for g, pct in grades:
        h = pct * 6
        p.draw_rect(fitz.Rect(x, base_y - h, x + 40, base_y), color=TEAL, fill=TEAL)
        p.insert_text((x + 12, base_y + 14), g, fontsize=9)
        p.insert_text((x + 8, base_y - h - 4), f"{pct}%", fontsize=8)
        x += 60
    for i in range(30):  # gridlines (also makes the page register as visual content)
        p.draw_line((80, base_y - i * 6), (84, base_y - i * 6), color=(0.5, 0.5, 0.5), width=0.3)
    p.insert_text((90, base_y + 32), "The most common grade was A (26% of students); 4% of grades were F.",
                  fontsize=9)
    doc.save(out / "Academic_Regulations_2026.pdf")


def syllabus(out: Path) -> None:
    doc = fitz.open()
    p, y = _page(doc, "CS201 Data Structures - Course Syllabus")
    y = _para(p, y, "Credits: 4 (3 lecture + 1 lab). Prerequisite: CS101 Programming Fundamentals.")
    units = [
        ("Unit 1: Introduction and Arrays", "Abstract data types, asymptotic notation (Big-O, Omega, Theta), "
         "arrays, dynamic arrays and amortised analysis."),
        ("Unit 2: Linked Lists, Stacks and Queues", "Singly, doubly and circular linked lists; stack and queue "
         "ADTs; applications such as expression evaluation and BFS."),
        ("Unit 3: Trees", "Binary trees, tree traversals (inorder, preorder, postorder), binary search trees, "
         "AVL trees and rotations, heaps and priority queues."),
        ("Unit 4: Graphs", "Graph representations, depth-first and breadth-first search, shortest paths "
         "(Dijkstra), minimum spanning trees (Prim and Kruskal)."),
        ("Unit 5: Hashing and Sorting", "Hash tables, collision resolution, quicksort, mergesort, heapsort and "
         "lower bounds for comparison sorting."),
    ]
    for head, body in units:
        y = _para(p, y, head, bold=True)
        y = _para(p, y, body)
    y = _para(p, y, "Textbook: Cormen et al., Introduction to Algorithms, 4th edition.")

    p, y = _page(doc, "CS201 Lab Manual - Experiments")
    y = _para(p, y, "Lab experiments are evaluated for 25 marks: 15 marks for weekly records and 10 marks for "
                    "the final lab examination. Students must complete at least 8 of the 10 experiments to be "
                    "eligible for the lab examination.")
    y = _para(p, y, "Figure 2: Binary search tree used in Experiment 6 (insertion and deletion).", size=9)
    nodes = {"50": (300, y + 30), "30": (200, y + 90), "70": (400, y + 90), "20": (150, y + 150),
             "40": (250, y + 150), "60": (350, y + 150), "80": (450, y + 150)}
    for a, b in [("50", "30"), ("50", "70"), ("30", "20"), ("30", "40"), ("70", "60"), ("70", "80")]:
        p.draw_line(nodes[a], nodes[b], color=NAVY, width=1)
    for label, (cx, cy) in nodes.items():
        p.draw_circle((cx, cy), 16, color=NAVY, fill=(0.88, 0.93, 0.97))
        p.insert_text((cx - 7, cy + 4), label, fontsize=10)
    for i in range(30):
        p.draw_line((60, y + 200 + i), (62, y + 200 + i), color=(1, 1, 1), width=0.1)
    doc.save(out / "CS201_Data_Structures_Syllabus.pdf")


def admission_notice(out: Path) -> None:
    doc = fitz.open()
    p, y = _page(doc, "Admission Notice 2026-27: B.Tech First Year")
    y = _para(p, y, "Applications are invited for admission to the first year of the B.Tech programme. "
                    "The last date to submit the online application is 30 June 2026. Spot admission, if seats "
                    "remain, will be held on 20 July 2026.")
    y = _para(p, y, "Documents required at the time of admission:", bold=True)
    y = _para(p, y, "1. Class 10 and Class 12 mark sheets (original and two photocopies)\n"
                    "2. Transfer certificate from the institution last attended\n"
                    "3. Community certificate, if claiming reservation\n"
                    "4. Two recent passport-size photographs\n"
                    "5. Proof of payment of the admission fee\n"
                    "6. Aadhaar card or another government photo ID")
    y = _para(p, y, "Note for final-year students: the project submission deadline for the 2026-27 batch is "
                    "15 April 2027.")

    # Page 2 is an image-only "scanned" page, to exercise the OCR path.
    scan = fitz.open()
    sp = scan.new_page(width=595, height=842)
    sp.insert_text((60, 90), "Hostel Rules (scanned copy)", fontsize=18, fontname="hebo")
    lines = ["Hostel gates close at 9:30 PM on all days.",
             "Visitors are allowed only on Sundays between 10 AM and 5 PM.",
             "Students must carry their hostel ID card at all times.",
             "Cooking appliances are not permitted in rooms."]
    for i, line in enumerate(lines):
        sp.insert_text((60, 140 + i * 32), line, fontsize=14)
    pix = sp.get_pixmap(dpi=110)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_image(page2.rect, stream=pix.tobytes("png"))
    doc.save(out / "Admission_Notice_2026.pdf")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "sample_docs"
    out.mkdir(parents=True, exist_ok=True)
    regulations(out)
    syllabus(out)
    admission_notice(out)
    print(f"Wrote sample documents to {out}")


if __name__ == "__main__":
    main()

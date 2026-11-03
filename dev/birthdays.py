from datetime import date

birthdays = {
    "Alex Kunz": date(2000, 1, 11),
    "Oliver Prenger": date(2000, 2, 18),
    "Brooke Becker": date(2000, 2, 20),
    "Abel Osorio-Morales": date(2000, 2, 25),
    "Logan White": date(2000, 3, 20),
    "Ryan Blanken": date(2000, 3, 22),
    "Ben Higgins": date(2000, 3, 23),
    "Aiden Neely": date(2000, 4, 11),
    "Maddox Bennett": date(2000, 4, 12),
    "Leah Schatz": date(2000, 4, 28),
    "Amit Singh": date(2000, 5, 2),
    "Dylan Goldstein": date(2000, 6, 3),
    "Kristina Sidorova": date(2000, 7, 9),
    "Jack Dunning": date(2000, 7, 31),
    "Lauren Millard": date(2000, 8, 2),
    "Alex Gillund": date(2000, 8, 7),
    "Braeden Howard": date(2000, 8, 10),
    "Isaac Dierker": date(2000, 8, 11),
    "Eli Davis": date(2000, 8, 12),
    "David 'D-Rod' Hartman": date(2000, 8, 28),
    "Josh Gephardt": date(2000, 9, 2),
    "Alex Troesser": date(2000, 9, 7),
    "Hayden Higgins": date(2000, 9, 18),
    "Jack Fels": date(2000, 9, 19),
    "Max Pedreros": date(2000, 9, 21),
#   "Justin Bowers": date(2000, 10, 16),
    "Adam Farr": date(2000, 11, 18),
    "Anshu Gilyaru": date(2000, 11, 24),
    "Aaron Jewett": date(2000, 12, 6),
    "Caleb Harris": date(2000, 12, 6)
}

def returnBirthdays(today=None):
    today = today or date.today()
    names = [
        name for name, bday in birthdays.items()
        if (bday.month, bday.day) == (today.month, today.day)
    ]
    if not names:
        return ""
    return "Happy Birthday " + " & ".join(names) + "!"

#!/usr/bin/env python3
import curses
import random
from collections import deque

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(1)
    stdscr.timeout(100)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    
    h, w = stdscr.getmaxyx()
    snake = deque([(w//4, h//2), (w//4-1, h//2), (w//4-2, h//2)])
    food = (w//2, h//2)
    direction = curses.KEY_RIGHT
    score = 0
    
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Snake Game - Score: {score} | WASD/Arrows to move, Q to quit", curses.color_pair(3))
        
        # Draw border
        for i in range(w-1):
            stdscr.addstr(1, i, '-')
            stdscr.addstr(h-2, i, '-')
        for i in range(1, h-1):
            stdscr.addstr(i, 0, '|')
            stdscr.addstr(i, w-2, '|')
        
        # Draw snake
        for i, (x, y) in enumerate(snake):
            stdscr.addstr(y, x, 'O' if i == 0 else 'o', curses.color_pair(1))
        
        # Draw food
        stdscr.addstr(food[1], food[0], '*', curses.color_pair(2))
        stdscr.refresh()
        
        # Get input
        key = stdscr.getch()
        if key in [ord('q'), ord('Q')]:
            break
        if key in [curses.KEY_UP, ord('w'), ord('W')] and direction != curses.KEY_DOWN:
            direction = curses.KEY_UP
        elif key in [curses.KEY_DOWN, ord('s'), ord('S')] and direction != curses.KEY_UP:
            direction = curses.KEY_DOWN
        elif key in [curses.KEY_LEFT, ord('a'), ord('A')] and direction != curses.KEY_RIGHT:
            direction = curses.KEY_LEFT
        elif key in [curses.KEY_RIGHT, ord('d'), ord('D')] and direction != curses.KEY_LEFT:
            direction = curses.KEY_RIGHT
        
        # Move snake
        head_x, head_y = snake[0]
        if direction == curses.KEY_UP:
            new_head = (head_x, head_y - 1)
        elif direction == curses.KEY_DOWN:
            new_head = (head_x, head_y + 1)
        elif direction == curses.KEY_LEFT:
            new_head = (head_x - 1, head_y)
        else:
            new_head = (head_x + 1, head_y)
        
        # Check collisions
        if (new_head[0] <= 0 or new_head[0] >= w-2 or
            new_head[1] <= 1 or new_head[1] >= h-2 or
            new_head in snake):
            stdscr.addstr(h//2, w//2-10, "GAME OVER! Press any key", curses.color_pair(2))
            stdscr.nodelay(0)
            stdscr.getch()
            break
        
        snake.appendleft(new_head)
        
        # Check if ate food
        if new_head == food:
            score += 10
            while True:
                food = (random.randint(2, w-3), random.randint(2, h-3))
                if food not in snake:
                    break
        else:
            snake.pop()

if __name__ == "__main__":
    curses.wrapper(main)

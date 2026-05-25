export class UndoStack {
  constructor(limit = 20) {
    this.limit = limit;
    this.undoStack = [];
    this.redoStack = [];
  }

  reset() {
    this.undoStack = [];
    this.redoStack = [];
  }

  push(snapshot) {
    this.undoStack.push(snapshot);
    if (this.undoStack.length > this.limit) this.undoStack.shift();
    this.redoStack.length = 0;
  }

  canUndo() { return this.undoStack.length > 1; }
  canRedo() { return this.redoStack.length > 0; }

  undo() {
    if (!this.canUndo()) return null;
    const cur = this.undoStack.pop();
    this.redoStack.push(cur);
    return this.undoStack[this.undoStack.length - 1];
  }

  redo() {
    if (!this.canRedo()) return null;
    const snap = this.redoStack.pop();
    this.undoStack.push(snap);
    return snap;
  }
}

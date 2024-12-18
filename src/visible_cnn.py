import pandas as pd
from torchvision import transforms
from torch.utils.data import Dataset, DataLoader, random_split
from PIL import Image
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import os


# Define CNN model for Voltorb Flip
class VoltorbFlipCNN(nn.Module):
    MODEL_PATH = "./weights/visible_cnn.pth"
    TRANSFORM = transforms.Compose([
        transforms.Resize((32, 32)),
        transforms.ToTensor()
    ])
    N_CLASSES = 13
    N_FEATURES = 45

    def __init__(self):
        super(VoltorbFlipCNN, self).__init__()
        self.conv1 = nn.Conv2d(3, 32, kernel_size=3, stride=1, padding=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, stride=1, padding=1)
        self.conv3 = nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1)
        
        # Determine the correct input size for self.fc1 by passing a dummy input
        self.flattened_size = self._get_flattened_size()
        self.fc1 = nn.Linear(self.flattened_size, 256)
        self.fc2 = nn.Linear(256, 585)  # n_classes * n_features

    def _get_flattened_size(self):
        # Pass a dummy input of the expected size through the conv layers
        with torch.no_grad():
            x = torch.zeros(1, 3, 32, 32)  # Dummy input with batch size 1 and 32x32 size
            x = F.relu(self.conv1(x))
            x = F.max_pool2d(x, 2)
            x = F.relu(self.conv2(x))
            x = F.max_pool2d(x, 2)
            x = F.relu(self.conv3(x))
            return x.view(1, -1).size(1)  # Flatten and get the size

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)
        x = F.relu(self.conv3(x))
        x = x.view(x.size(0), -1)  # Flatten for the fully connected layer
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        x = F.sigmoid(x)
        return x

    def load_weights(self):
        self.load_state_dict(torch.load(self.MODEL_PATH, weights_only=True))

    def predict(self, input_image: Image):
        self.eval()
        with torch.no_grad():
            # preprocess and transform input data
            input_image = torch.unsqueeze(self.TRANSFORM(input_image.convert('RGB')), 0)

            # forward pass
            output = self.forward(input_image)
            _, decoded_output = torch.max(output.view(-1, VoltorbFlipCNN.N_CLASSES), 1)

            # return predictions
            return decoded_output


# Custom dataset for loading images with state labels
class VoltorbFlipScreenshotDataset(Dataset):
    def __init__(self, image_folder, visible_states, transform=None):
        self.image_folder = image_folder
        self.visible_states = visible_states
        self.transform = transform

    def __len__(self):
        return len(self.visible_states)

    def __getitem__(self, idx):
        img_path = os.path.join(self.image_folder, f"{idx}.png")
        image = Image.open(img_path).convert('RGB')
        labels = self.visible_states.iloc[idx].values[1:]
        encoded_labels = F.one_hot(torch.tensor(labels), num_classes=VoltorbFlipCNN.N_CLASSES).flatten()

        if self.transform:
            image = self.transform(image)
        return image, encoded_labels


# Trainer class
class Trainer:
    def __init__(self, model, optimizer, loss_fn, train_loader, test_loader, model_path, episodes=5):
        """
        Initialize the Trainer with model, optimizer, loss function, dataloaders, and number of episodes.
        """
        self.model = model
        self.optimizer = optimizer
        self.loss_fn = loss_fn
        self.train_loader = train_loader
        self.test_loader = test_loader
        self.episodes = episodes
        self.model_path = model_path

    def train(self):
        """
        Train the model over the specified number of episodes.
        """
        self.model.train()
        for episode in range(self.episodes):
            total_loss = 0.0
            for screenshots, labels in self.train_loader:
                output = self.model(screenshots)
                loss = self.loss_fn(output, labels.float())
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
                total_loss += loss.item()
            print(f"Episode {episode + 1}/{self.episodes}, Loss: {total_loss:.4f}")

    def evaluate(self):
        """
        Evaluate the model on the test dataset and calculate accuracy.
        """
        self.model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for screenshots, labels in self.test_loader:
                output = self.model(screenshots)
                _, decoded_output = torch.max(output.view(-1, VoltorbFlipCNN.N_CLASSES), 1)
                _, decoded_labels = torch.max(labels.view(-1, VoltorbFlipCNN.N_CLASSES), 1)
                total += decoded_labels.shape.numel()
                correct += (decoded_output == decoded_labels).sum().item()
        accuracy = correct / total * 100
        print(f"Test Accuracy: {accuracy:.2f}%")
        return accuracy

    def save_model(self):
        """
        Save the model's weights to a file.
        """
        torch.save(self.model.state_dict(), self.model_path)
        print(f"Model weights saved to {self.model_path}")

    def print_weights(self):
        """
        Print the model's weights.
        """
        for name, param in self.model.named_parameters():
            print(f"Layer: {name} | Weights: {param}")


# Main function
def main():
    # Load the CSV file for visible states
    visible_states = pd.read_csv('./training_data/visible_states.csv')  # Assuming this file contains labels for each screenshot

    # Paths to images and transformation
    transform = VoltorbFlipCNN.TRANSFORM
    image_folder = './training_data/screenshots/'  # Replace with the actual path to the screenshots

    # Load dataset
    screenshot_dataset = VoltorbFlipScreenshotDataset(
        image_folder=image_folder,
        visible_states=visible_states,
        transform=transform
    )

    # Split dataset into 80% training and 20% testing
    train_size = int(0.8 * len(screenshot_dataset))
    test_size = len(screenshot_dataset) - train_size
    train_dataset, test_dataset = random_split(screenshot_dataset, [train_size, test_size])

    # Create DataLoaders for training and testing
    train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=16, shuffle=False)

    # Initialization
    cnn_model = VoltorbFlipCNN()
    optimizer = optim.Adam(cnn_model.parameters(), lr=0.001)
    loss_fn = nn.BCELoss()

    # Training and Evaluation
    trainer = Trainer(
        cnn_model,
        optimizer,
        loss_fn,
        train_loader,
        test_loader,
        model_path=VoltorbFlipCNN.MODEL_PATH,
        episodes=50,
    )
    trainer.train()
    trainer.evaluate()
    trainer.save_model()
    trainer.print_weights()


# Entry point
if __name__ == "__main__":
    main()




